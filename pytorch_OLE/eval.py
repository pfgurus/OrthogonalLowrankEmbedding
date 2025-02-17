'''
Evaluation script for CIFAR-10/100
Copyright (c) Wei YANG, 2017

Modifications for use with Orthogonal Lowrank Embedding by Jose Lezama, 2017
'''
# from __future__ import print_function

import argparse
import os
import shutil
import time
import random

import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data as data
import torchvision.transforms as transforms
import torchvision.datasets as datasets
import models.cifar as models

from utils import Bar, Logger, AverageMeter, accuracy, mkdir_p, savefig


# OLE Loss
from OLE import *
from backup import *
import uuid
import sys
from datetime import datetime
import numpy as np
import scipy.io

import scipy as sp
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
import inspect



model_names = sorted(name for name in models.__dict__
    if name.islower() and not name.startswith("__")
    and callable(models.__dict__[name]))


parser = argparse.ArgumentParser(description='PyTorch CIFAR10/100 Evaluation')
# Datasets
parser.add_argument('-d', '--dataset', default='cifar100', type=str)
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
# Optimization options
parser.add_argument('--epochs', default=164, type=int, metavar='N',
                    help='number of total epochs to run')
parser.add_argument('--start-epoch', default=0, type=int, metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('--train-batch', default=64, type=int, metavar='N',
                    help='train batchsize')
parser.add_argument('--test-batch', default=64, type=int, metavar='N',
                    help='test batchsize')
parser.add_argument('--lr', '--learning-rate', default=0.1, type=float,
                    metavar='LR', help='initial learning rate')
parser.add_argument('--drop', '--dropout', default=0, type=float,
                    metavar='Dropout', help='Dropout ratio')
parser.add_argument('--schedule', type=int, nargs='+', default=[150, 225],
                        help='Decrease learning rate at these epochs.')
parser.add_argument('--gamma', type=float, default=0.1, help='LR is multiplied by gamma on schedule.')
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum')
parser.add_argument('--weight-decay', '--wd', default=5e-4, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
# Checkpoints
parser.add_argument('-c', '--checkpoint', default='checkpoint', type=str, metavar='PATH',
                    help='path to save checkpoint (default: checkpoint)')
parser.add_argument('--resume', default='', type=str, metavar='PATH',
                    help='path to latest checkpoint (default: none)')
# Architecture
parser.add_argument('--arch', '-a', metavar='ARCH', default='resnet',
                    choices=model_names,
                    help='model architecture: ' +
                        ' | '.join(model_names) +
                        ' (default: resnet)')
parser.add_argument('--depth', type=int, default=110, help='Model depth.')
parser.add_argument('--cardinality', type=int, default=8, help='Model cardinality (group).')
parser.add_argument('--widen-factor', type=int, default=4, help='Widen factor. 4 -> 64, 8 -> 128, ...')
parser.add_argument('--growthRate', type=int, default=12, help='Growth rate for DenseNet.')
parser.add_argument('--compressionRate', type=int, default=2, help='Compression Rate (theta) for DenseNet.')
# Miscs
parser.add_argument('--manualSeed', type=int, help='manual seed')
parser.add_argument('-e', '--evaluate', dest='evaluate', action='store_true',
                    help='evaluate model on validation set')
# Device options
parser.add_argument('--gpu_id', default='0', type=str,
                    help='id(s) for CUDA_VISIBLE_DEVICES')
# OLE Loss
parser.add_argument('--lambda_', type=float, default=0.25, help='OLE loss is multiplied by lambda_.')
parser.add_argument( '--no_augment', dest='no_augment', action='store_true',
                    help='do not perform data augmentation')
parser.add_argument( '--validation', dest='validation', action='store_true',
                     help='do validation (trains on 90%% of training set, evaluates on remaining 10%%)')
parser.add_argument( '--no_print', dest='no_print', action='store_true',
                    help='do not print to file')


args = parser.parse_args()
state = {k: v for k, v in args._get_kwargs()}

# Validate dataset
assert args.dataset == 'cifar10' or args.dataset == 'cifar100', 'Dataset can only be cifar10 or cifar100.'

# Use CUDA
os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu_id
use_cuda = torch.cuda.is_available()

# Random seed
if args.manualSeed is None:
    args.manualSeed = random.randint(1, 10000)
random.seed(args.manualSeed)
torch.manual_seed(args.manualSeed)
if use_cuda:
    torch.cuda.manual_seed_all(args.manualSeed)

best_acc = 0  # best test accuracy
use_OLE = False


def main():


    # Data
    print('==> Preparing dataset %s' % args.dataset)

    transform_test = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
    ])

    if args.no_augment:
        print ('NO DATA AUGMENTATION')
        transform_train = transform_test
    else:
        print ('USE DATA AUGMENTATION')
        transform_train = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])

    if args.dataset == 'cifar10':
        dataloader = datasets.CIFAR10
        num_classes = 10
    else:
        dataloader = datasets.CIFAR100
        num_classes = 100


    trainset = dataloader(root='./data', train=True, download=True, transform=transform_train)
    trainloader = data.DataLoader(trainset, batch_size=args.train_batch, shuffle=True, num_workers=args.workers)

    testset = dataloader(root='./data', train=False, download=False, transform=transform_test)
    testloader = data.DataLoader(testset, batch_size=args.test_batch, shuffle=False, num_workers=args.workers)

    # Model
    print("==> creating model '{}'".format(args.arch))
    if args.arch.startswith('resnext'):
        model = models.__dict__[args.arch](
                    cardinality=args.cardinality,
                    num_classes=num_classes,
                    depth=args.depth,
                    widen_factor=args.widen_factor,
                    dropRate=args.drop,
                )
    elif args.arch.startswith('densenet'):
        model = models.__dict__[args.arch](
                    num_classes=num_classes,
                    depth=args.depth,
                    growthRate=args.growthRate,
                    compressionRate=args.compressionRate,
                    dropRate=args.drop,
                )
    elif args.arch.startswith('wrn'):
        model = models.__dict__[args.arch](
                    num_classes=num_classes,
                    depth=args.depth,
                    widen_factor=args.widen_factor,
                    dropRate=args.drop,
                )
    elif args.arch.endswith('resnet'):
        model = models.__dict__[args.arch](
                    num_classes=num_classes,
                    depth=args.depth,
                )
    else:
        model = models.__dict__[args.arch](num_classes=num_classes)

    model = torch.nn.DataParallel(model).cuda()
    cudnn.benchmark = True
    print('    Total params: %.2fM' % (sum(p.numel() for p in model.parameters())/1000000.0))

    # use OLE loss?
    global use_OLE

    if args.lambda_ > 0:
        print ('USE OLE')
        use_OLE = True
    else:
        print ('NO OLE')
        use_OLE = False


    if use_OLE:
        assert(args.train_batch == args.test_batch)
        print ('creating OLE criterion with lambda_=', args.lambda_)
        criterion = [nn.CrossEntropyLoss()] + [OLELoss]
    else:
        criterion = [nn.CrossEntropyLoss()]

    optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum, weight_decay=args.weight_decay)

    # Resume
    title = 'cifar-10-' + args.arch
    if args.resume:
        # Load checkpoint.
        print('==> Resuming from checkpoint..')
        assert os.path.isfile(args.resume), 'Error: no checkpoint directory found!'
        args.checkpoint = os.path.join(os.path.dirname(args.resume), 'fine_tune')

        if not os.path.isdir(args.checkpoint):
            mkdir_p(args.checkpoint)


        checkpoint = torch.load(args.resume)
        best_acc = checkpoint['best_acc']
        start_epoch = 0 # checkpoint['epoch']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
    else:
        pass



    ############ EVALUATE

    print('\nEvaluation only')
    test_loss, test_acc, features, scores, labels = test(testloader, model, criterion, start_epoch, use_cuda)
    print(' Test Loss:  %.8f, Test Acc:  %.2f' % (test_loss, test_acc))
    print ('features shape', features.shape, 'scores shape', scores.shape, 'labels shape', labels.shape)

    plot_tsne_embeddings(features, labels, args.resume, args.resume.split('/')[-2])

    U, S, V = sp.linalg.svd(features, full_matrices = False, lapack_driver='gesvd')

    obj_all = np.sum(S)
    S = S/np.max(S)


    savefolder = '/'.join(args.resume.split('/')[:-1])
    foldername = args.resume.split('/')[-2]


    print('foldername is', foldername)
    # create figures folder
    figuresfolder = 'figures/curves/'
    os.system('mkdir -p %s' % figuresfolder)

    print ('saving figure of', savefolder)

    # plot and save
    fig = plt.figure(figsize=(6*3.13,4*3.13))
    plt.plot(S)
    plt.grid()
    plt.title('%s acc: %f' % (foldername, test_acc))
    plt.savefig('%s/%s_singular_values.png' % (figuresfolder, foldername))
    plt.close()

    # save features
    print ('saving data ')
    scipy.io.savemat('%s/%s_result.mat' % (figuresfolder, foldername), mdict={'features': features, 'scores':scores, 'labels':labels, 'acc':test_acc})


    ymine = np.argmax(scores,1)

    acc = np.sum(ymine==labels.astype(int))/(labels.shape[0])
    print ('accuracy %2.6f' % acc)



    print('Done!')



def test(testloader, model, criterion, epoch, use_cuda):
    global best_acc


    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()
    lowrank = AverageMeter()
    total_loss = AverageMeter()

    # switch to evaluate mode
    model.eval()

    features = None


    end = time.time()
    bar = Bar('Processing', max=len(testloader))
    for batch_idx, (inputs, targets) in enumerate(testloader):
        # measure data loading time
        data_time.update(time.time() - end)

        if use_cuda:
            inputs, targets = inputs.cuda(), targets.cuda()
        inputs, targets = torch.autograd.Variable(inputs, volatile=True), torch.autograd.Variable(targets)

        # compute output
        outputs = model(inputs)

        # save features
        features_i = outputs[1].data.cpu().numpy()
        scores_i = outputs[0].data.cpu().numpy()
        labels_i = targets.data.cpu().numpy()


        if not np.any(features):
            features = np.copy(features_i)
            scores = np.copy(scores_i)
            labels = np.copy(labels_i)
        else:
            features = np.concatenate((features, features_i), 0)
            scores = np.concatenate((scores, scores_i), 0)
            labels = np.concatenate((labels, labels_i), 0)


        # criterion is a list composed of crossentropy loss and OLE loss.
        losses_list = [-1,-1]

        # output_Var contains scores in the first element and features in the second element
        loss = 0
        for cix, crit in enumerate(criterion):
            if inspect.isclass(crit):
                losses_list[cix] = crit.apply(outputs[cix], targets)[0]
            else:
                losses_list[cix] = crit(outputs[cix], targets)
            loss += losses_list[cix]


        # measure accuracy and record loss
        prec1, prec5 = accuracy(outputs[0].data, targets.data, topk=(1, 5))
        losses.update(losses_list[0].item(), inputs.size(0))
        top1.update(prec1.item(), inputs.size(0))
        top5.update(prec5.item(), inputs.size(0))
        total_loss.update(loss.item(), inputs.size(0))

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        # plot progress
        bar.suffix  = '[{epoch: d}] ({batch}/{size}) Data: {data:.3f}s | Batch: {bt:.3f}s | Total: {total:} | ETA: {eta:} | Loss: {loss:.4f} | top1: {top1: .4f} | top5: {top5: .4f} | OLE: {lowrank: .4f}  | total loss: {total_loss: .4f} '.format(
                    epoch=epoch,
                    batch=batch_idx + 1,
                    size=len(testloader),
                    data=data_time.avg,
                    bt=batch_time.avg,
                    total=bar.elapsed_td,
                    eta=bar.eta_td,
                    loss=losses.avg,
                    top1=top1.avg,
                    top5=top5.avg,
                    lowrank=lowrank.avg,
                    total_loss = total_loss.avg,
                    )
        bar.next()

    bar.finish()
    return (losses.avg, top1.avg, features, scores, labels)

def plot_tsne_embeddings(features, labels, savefolder, foldername):
    # create figures folder
    figuresfolder = 'figures/embeddings/'
    os.system('mkdir -p %s' % figuresfolder)
    print ('saving figure of', savefolder)

    # Get features for 10 random labels
    labelset_10 = np.random.choice(np.unique(labels), min(10, len(np.unique(labels))), replace=False)
    features_10 = np.zeros((0, features.shape[1]))
    labels_10 = np.zeros((0))
    for label in labelset_10:
        features_10 = np.concatenate((features_10, features[labels==label,:]), 0)
        labels_10 = np.concatenate((labels_10, labels[labels==label]), 0)

    # DO Tsne
    from sklearn.manifold import TSNE
    tsne = TSNE(n_components=2, random_state=0)
    features_10 = tsne.fit_transform(features_10)

    # plot and save
    fig = plt.figure(figsize=(6*3.13,4*3.13))
    plt.scatter(features_10[:,0], features_10[:,1], c=labels_10)
    plt.grid()
    plt.title('%s' % (foldername))
    plt.savefig('%s/%s_epoch.png' % (figuresfolder, foldername))
    plt.close()


if __name__ == '__main__':
    main()
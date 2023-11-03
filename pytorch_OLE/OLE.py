import torch
from torch.autograd import Variable, Function

import numpy as np
import scipy as sp
import scipy.linalg as linalg


# Inherit from Function
class OLELoss(Function):

    @staticmethod
    def forward(ctx, X, y):
        weight = 0.1
        X = X.cpu().numpy()
        y = y.cpu().numpy()

        classes = np.unique(y)
        C = classes.size

        N, D = X.shape

        lambda_ = 1.
        DELTA = 1.

        # gradients initialization
        Obj_c = 0
        dX_c = np.zeros((N, D))
        Obj_all = 0;
        dX_all = np.zeros((N, D))

        eigThd = 1e-6  # threshold small eigenvalues for a better subgradient

        # compute objective and gradient for first term \sum ||TX_c||*
        for c in classes:
            A = X[y == c, :]

            # SVD
            U, S, V = sp.linalg.svd(A, full_matrices=False, lapack_driver='gesvd')

            V = V.T
            nuclear = np.sum(S);

            ## L_c = max(DELTA, ||TY_c||_*)-DELTA

            if nuclear > DELTA:
                Obj_c += nuclear;

                # discard small singular values
                r = np.sum(S < eigThd)
                uprod = U[:, 0:U.shape[1] - r].dot(V[:, 0:V.shape[1] - r].T)

                dX_c[y == c, :] += uprod
            else:
                Obj_c += DELTA

        # compute objective and gradient for secon term ||TX||*

        U, S, V = sp.linalg.svd(X, full_matrices=False, lapack_driver='gesvd')  # all classes

        V = V.T

        Obj_all = np.sum(S);

        r = np.sum(S < eigThd)

        uprod = U[:, 0:U.shape[1] - r].dot(V[:, 0:V.shape[1] - r].T)

        dX_all = uprod

        obj = (Obj_c - lambda_ * Obj_all) / N * weight

        dX = (dX_c - lambda_ * dX_all) / N * weight

        ctx.save_for_backward(torch.from_numpy(dX).cuda())
        return torch.FloatTensor([float(obj)]).cuda()

    @staticmethod
    def backward(ctx, grad_output):
        # print self.dX
        return ctx.saved_tensors[0], None

"""
Methods for creating summary statistics and their SE for survey data.

The main classes are:

  * SurveyDesign : Parent class that creates attributes for easy
  implementation of other methods. Attributes include relabeled
  clusters, number of clusters per strata, etc.

  * SurveyStat : implements methods to calculate the standard
  error of each statistic via either the bootstrap or jackknife

  * SurveyMean : Calculates the mean of each column

  * SurveyTotal : Calculates the total of each column

  * SurveyQuantile: Calculates the specified quantile[s] of each column
"""

import numpy as np
# import pandas as pd


class SurveyDesign(object):
    """
    Description of a survey design, used by most methods
    implemented in this module.

    Parameters
    -------
    strata : array-like or None
        Strata for each observation. If none, an array
        of ones is constructed
    cluster : array-like or None
        Cluster for each observation. If none, an array
        of ones is constructed
    weights : array-like or None
        The weight for each observation. If none, an array
        of ones is constructed
    nest : boolean
        allows user to specify if PSU's with the same
        PSU number in different strata are treated as distinct PSUs.

    Attributes
    ----------
    weights : (n, ) array
        The weight for each observation
    nstrat : integer
        The number of district strata
    sclust : (n, ) array
        The relabeled cluster array from 0, 1, ..
    strat : (n, ) array
        The related strata array from 0, 1, ...
    clust_per_strat : (self.nstrat, ) array
        Holds the number of clusters in each stratum
    strat_for_clust : ndarray
        The stratum for each cluster
    nclust : integer
        The total number of clusters across strata
    """

    def __init__(self, strata=None, cluster=None, weights=None,
                 rep_weights=None, fpc=None, cov_method='jack', nest=True):
        # Ensure method for SE is supported
        if cov_method not in ["boot", 'mean_boot', 'jack']:
            raise ValueError("Method %s not supported" % cov_method)
        else:
            self.cov_method = cov_method

        self.rep_weights = rep_weights

        if self.rep_weights is not None:
            if strata is not None or cluster is not None:
                raise ValueError("If providing rep_weights, do not provide \
                             cluster or strata")
            if weights is None:
                self.weights = np.ones(self.rep_weights.shape[0])
            else:
                self.weights = weights
            return

        strata, cluster, self.weights, \
            self.fpc = self._check_args(strata, cluster, weights, fpc)

        # Recode strata and clusters as integer values 0, 1, ...
        _, self.strat = np.unique(strata, return_inverse=True)
        _, clust = np.unique(cluster, return_inverse=True)

        # the number of distinct strata
        self.nstrat = max(self.strat) + 1

        # If requested, recode the PSUs to be sure that the same PSU # in
        # different strata are treated as distinct PSUs. This is the same
        # as the nest option in R.
        if nest:
            m = max(clust) + 1
            sclust = clust + m*self.strat
            _, self.sclust = np.unique(sclust, return_inverse=True)
        else:
            self.sclust = clust.copy()

        # The number of clusters per stratum
        _, ii = np.unique(self.sclust, return_index=True)
        self.clust_per_strat = np.bincount(self.strat[ii])

        # The stratum for each cluster
        self.strat_for_clust = self.strat[ii]

        # The fpc for each cluster
        self.fpc = self.fpc[ii]

        # The total number of clusters over all stratum
        self.nclust = np.sum(self.clust_per_strat)

        # get indices of all clusters within a stratum
        self.ii = []
        for s in range(self.nstrat):
            self.ii.append(np.flatnonzero(self.strat_for_clust == s))

    def __str__(self):
        """
        The __str__ method for our data
        """
        summary_list = ["Number of observations: ", str(len(self.strat)),
                        "Sum of weights: ", str(self.weights.sum()),
                        "Number of strata: ", str(self.nstrat),
                        "Number of clusters per stratum: ", str(self.clust_per_strat),
                        "Method to compute SE: ", self.cov_method]

        return "\n".join(summary_list)

    def _check_args(self, strata, cluster, weights, fpc):
        """
        Minor error checking to make sure user supplied any of
        strata, cluster, or weights. For unspecified subgroup labels
        an array of ones is created

        Parameters
        ----------
        strata : array-like or None
            Strata for each observation. If none, an array
            of ones is constructed
        cluster : array-like or None
            Cluster for each observation. If none, an array
            of ones is constructed
        weights : array-like or None
            The weight for each observation. If none, an array
            of ones is constructed

        Returns
        -------
        vals[0] : ndarray
            array of the strata labels
        vals[1] : ndarray
            array of the cluster labels
        vals[2] : ndarray
            array of the observation weights
        """
        if all([x is None for x in (strata, cluster, weights)]):
            raise ValueError("""At least one of strata, cluster, rep_weights, and weights
                             musts not be None""")
        v = [len(x) for x in (strata, cluster, weights) if x is not None]
        if len(set(v)) != 1:
            raise ValueError("""lengths of strata, cluster, and weights
                             are not compatible""")
        n = v[0]
        vals = []
        for x in (strata, cluster, weights):
            if x is None:
                vals.append(np.ones(n))
            else:
                vals.append(np.asarray(x))

        if fpc is None:
            vals.append(np.zeros(n))
        else:
            vals.append(np.asarray(fpc))

        return vals[0], vals[1], vals[2], vals[3]

    def get_rep_weights(self, c=None, bsn=None):
        """
        Returns replicate weights if provided, else computes rep weights
        and returns them.

        Parameters
        ----------
        c : integer or None
            Represents which cluster to leave out when computing
            'delete 1' jackknife replicate weights
        bsn : integer or None
            bootstrap mean-weight adjustment. Value of bsn is the # of
            bootstrap replicate-weight variables were used to
            generate each bootstrap

        Returns
        -------
        rep_weights : ndarray
            Either the provided rep_weights when a design object
            was created, or calculated rep_weights from jackknife,
            bootstrap, or mean bootstrap
        """
        if self.rep_weights is not None:
            # should rep_weights be a list of arrays or a ndarray
            return self.rep_weights[:, c]
        if self.cov_method == 'jack':
            return self._jackknife_rep_weights(c)
        elif self.cov_method == 'boot':
            return self._bootstrap_weights()
        else:
            return self._mean_bootstrap_weight(bsn)

    def _jackknife_rep_weights(self, c):
        """
        Computes 'delete 1' jackknife replicate weights

        Parameters
        ----------
        c : integer or None
            Represents which cluster to leave out when computing
            'delete 1' jackknife replicate weights

        Returns
        -------
        w : ndarray
            Augmented weight
        """
        # get stratum that the cluster belongs in
        s = self.strat_for_clust[c]
        nh = self.clust_per_strat[s]
        w = self.weights.copy()
        # all weights within the stratum are modified
        w[self.strat == s] *= nh / float(nh - 1)
        # but if you're within the cluster to be removed, set as 0
        w[self.sclust == c] = 0
        return w

    def _bootstrap_weights(self):
        """
        Computes bootstrap replicate weight

        Returns
        -------
        w : ndarray
            Augmented weight
        """
        w = self.weights.copy()
        clust_count = np.zeros(self.nclust)
        for s in range(self.nstrat):
            # how to handle strata w/ only one cluster?
            w[self.strat == s] *= float(self.clust_per_strat[s] - 1) \
                                         / self.clust_per_strat[s]
            # If there is only one cluster then weights wont change
            if self.clust_per_strat[s] == 1:
                continue

            # resample array of clusters
            ii_resample = np.random.choice(self.ii[s], size=(self.clust_per_strat[s]-1))
            # accumulate number of times cluster i was resampled
            clust_count += np.bincount(ii_resample,
                                       minlength=max(self.sclust)+1)

        w *= clust_count[self.sclust]
        return w

    def _mean_bootstrap_weight(self, bsn):
        """
        Computes mean bootstrap replicate weight

        Parameters
        ----------
        bsn : integer
            Mean bootstrap averages the number of resampled clusters over bsn
        Returns
        -------
        w : ndarray
            Augmented weight
        """
        clust_count = np.zeros(self.design.nclust)
        w = self.weights.copy()
        # for each replicate, I accumulate bsn number of times?
        for b in range(bsn):
            for s in range(self.nstrat):
                w[self.strat == s] *= ((float(self.clust_per_strat[s] - 1) /
                                        self.clust_per_strat[s])**(1/bsn))
                # If there is only one or two clusters then weights wont change
                if (self.clust_per_strat[s] == 1 or self.clust_per_strat[s] == 2):
                    continue
                # resample array of clusters in strata s
                ii_resample = np.random.choice(self.ii[s], size=(self.clust_per_strat[s]-1))
                # accumulate number of times cluster i was resampled
                clust_count += np.bincount(ii_resample,
                                           minlength=max(self.sclust)+1)
        # avg number of times cluster i was resampled
        clust_count /= bsn
        # augment weights
        w *= clust_count[self.sclust]
        return w


class SurveyStat(object):
    """
    Estimation and inference for summary statistics in complex surveys.

    Parameters
    -------
    design : SurveyDesign object

    Attributes
    ----------
    est : ndarray
        The point estimates of the statistic, calculated on the columns
        of data.
    vcov : ndarray
        The variance-covariance of the estimates.
    pseudo : ndarray
        The jackknife pseudo-values.
    """

    def __init__(self, design, mse=False):
        self.design = design
        self.mse = mse

    def _bootstrap(self, replicates=None, bsn=None):
        """
        Calculates bootstrap standard errors

        Parameters
        ----------
        stat : object
            Object of class SurveyMean, SurveyTotal, SurveyPercentile, etc
        replicates : integer
            The number of replicates that the user wishes to specify

        Returns
        -------
        est : ndarray
            The point estimates of the statistic, calculated on the columns
            of data.
        vcov : ndarray
            The variance-covariance of the estimates.
        """
        est = self._stat(self.design.weights)

        jdata = []
        for i in range(replicates):
            w = self.design.get_rep_weights(i, bsn=bsn)
            jdata.append(self._stat(w))
        jdata = np.asarray(jdata)
        if self.mse:
            print("mse specified")
            jdata -= est
        else:
            jdata -= jdata.mean(0)
        self.vcov = np.dot(jdata.T, jdata) / replicates
        if self.vcov.ndim == 2:
            self.stderr = np.sqrt(np.diag(self.vcov))
        else:
            self.stderr = np.sqrt(self.vcov)
        return est, self.vcov, self.stderr

    def _jackknife(self):
        """
        Jackknife variance estimation for survey data.

        Parameters
        ----------
        stat : object
            Object of class SurveyMean, SurveyTotal, SurveyPercentile, etc

        Returns
        -------
        est : ndarray
            The point estimates of the statistic, calculated on the columns
            of data.
        vcov : square ndarray
            The variance-covariance matrix of the estimates, obtained using
            the (drop 1) jackknife procedure.
        pseudo : ndarray
            The jackknife pseudo-values.
        """
        est = self._stat(self.design.weights)

        jdata = []
        try:
            k = self.design.nclust
        except AttributeError:
            k = self.design.rep_weights.shape[1]
        # for each cluster
        for c in range(k):
            # get jackknife weights
            w = self.design.get_rep_weights(c=c)
            jdata.append(self._stat(w))
        jdata = np.asarray(jdata)
        if self.mse:
            print('mse specified')
            jdata -= est
        else:
            if self.design.rep_weights is None:
                for s in range(self.design.nstrat):
                    # center the 'delete 1' statistic
                    jdata[self.design.ii[s], :] -= jdata[self.design.ii[s],
                                                         :].mean(0)
            else:
                jdata -= jdata.mean(0)
        print(jdata)

        if self.design.rep_weights is None:
            nh = self.design.clust_per_strat[self.design.strat_for_clust].astype(np.float64)
            _pseudo = jdata + nh[:, None] * (np.dot(self.design.weights,
                                                self.data) - jdata)
            mh = np.sqrt((nh - 1) / nh)
            fh = np.sqrt(1 - self.design.fpc)
            jdata = fh[:, None] * mh[:, None] * jdata
        else:
            nh = self.design.rep_weights.shape[1]
            mh = np.sqrt((nh - 1) / nh)
            jdata *= mh
        self.vcov = np.dot(jdata.T, jdata)
        if self.vcov.ndim == 2:
            self.stderr = np.sqrt(np.diag(self.vcov))
        else:
            self.stderr = np.sqrt(self.vcov)
        return est, self.vcov, self.stderr


class SurveyMean(SurveyStat):
    """
    Calculates the mean for each column.

    Parameters
    -------
    design : SurveyDesign object
    data : ndarray
        nxp array of the data to calculate the mean on
    method: string
        User inputs whether to get bootstrap or jackknife SE

    Attributes
    ----------
    data : ndarray
        The data which to calculate the mean on
    design :
        Points to the SurveyDesign object
    est : ndarray
        The point estimates of the statistic, calculated on the columns
        of data.
    vcov : ndarray
        The variance-covariance of the estimates.
    pseudo : ndarray
        The jackknife pseudo-values.
    """
    def __init__(self, design, data, mse=False, replicates=None, bsn=None):
        super().__init__(design, mse)
        if len(data.shape) == 2:
            self.data = np.asarray(data)
        else:
            self.data = np.asarray(data.reshape(len(data),1))
        if self.design.cov_method == "jack":
            self.est, self.vcov, self.stderr = self._jackknife()
        else:
            self.est, self.vcov, self.stderr = self._bootstrap(replicates, bsn)

    def _stat(self, weights):
        """
        Returns calculation of mean.

        Parameters
        ----------
        weights : np.array
            The weights used to calculate the mean, will either be
            original design weights or recalculated weights via jk,
            boot, etc

        Returns
        -------
        An array containing the statistic calculated on the columns
        of the dataset.
        """

        return np.dot(weights, self.data) / np.sum(weights)


class SurveyTotal(SurveyStat):
    """
    Calculates the total for each column.

    Parameters
    -------
    design : SurveyDesign object
    data : ndarray
        nxp array of the data to calculate the total on
    method: string
        User inputs whether to get bootstrap or jackknife SE

    Attributes
    ----------
    data : ndarray
        The data which to calculate the mean on
    design :
        Points to the SurveyDesign object
    est : ndarray
        The point estimates of the statistic, calculated on the columns
        of data.
    vcov : ndarray
        The variance-covariance of the estimates.
    pseudo : ndarray
        The jackknife pseudo-values.
    """
    def __init__(self, design, data, replicates=None, mse=False, bsn=None):
        super().__init__(design, mse)
        if len(data.shape) == 2:
            self.data = np.asarray(data)
        else:
            self.data = np.asarray(data.reshape(len(data),1))
        if self.design.cov_method == "jack":
            self.est, self.vcov, self.stderr = self._jackknife()
        else:
            self.est, self.vcov, self.stderr = self._bootstrap(replicates, bsn)

    def _stat(self, weights):
        """
        Returns calculation of mean.

        Parameters
        ----------
        weights : np.array
            The weights used to calculate the mean, will either be
            original design weights or recalculated weights via jk,
            boot, etc

        Returns
        -------
        An array containing the statistic calculated on the columns
        of the dataset.
        """
        return np.dot(weights, self.data)


class SurveyQuantile(SurveyStat):
    """
    Calculates the quantiles[s] for each column.

    Parameters
    -------
    design : SurveyDesign object
    data : ndarray
        nxp array of the data to calculate the mean on
    parameter: array-like
        array of quantiles to calculate for each column

    Attributes
    ----------
    data : ndarray
        The data which to calculate the quantiles on
    design :
        Points to the SurveyDesign object
    est : ndarray
        The point estimates of the statistic, calculated on the columns
        of data.
    quantile : ndarray
        The quantile[s] to calculate for each column
    vcov : ndarray
        The variance-covariance of the estimates.
    pseudo : ndarray
        The jackknife pseudo-values.
    """
    def __init__(self, design, data, quantile, replicates=None, mse=False,
                 bsn=None):
        if len(data.shape) == 2:
            self.data = np.asarray(data)
        else:
            self.data = np.asarray(data.reshape(len(data),1))
        super().__init__(design, mse)
        self.quantile = np.asarray(quantile)

        # give warning if user entered in quantile bigger than one
        if (self.quantile.min() < 0 or self.quantile.max > 1):
            raise ValueError("quantile[s] should be within [0, 1]")
        self.n_cw = len(self.design.weights)

        # get quantile[s] for each column
        self.est = [0] * self.data.shape[1]
        # need to call this several times
        self.std = [0] * self.data.shape[1]
        if self.design.cov_method == "jack":
            for index in range(self.data.shape[1]):
                self.est[index], self.std[index] = self._jackknife()
        else:
            for index in range(self.data.shape[1]):
                self.est[index], self.std[index] = self._bootstrap()

    def _stat(self, weights, col_index):
        quant_list = []
        cw = np.cumsum(weights)
        sorted_data = np.sort(self.data[:, col_index])
        q = self.quantile.copy() * cw[-1]
        # find index i such that self.cumsum_weights[i] >= q
        ind = np.searchsorted(cw, q)

        for i, pos in enumerate(ind):
            # if searchsorted returns length of list
            # return last observation
            if pos in np.array([self.n_cw - 1, self.n_cw]):
                quant_list.append(sorted_data[-1])
                continue
            if (cw[pos] == q[i]):
                quant_list.append((sorted_data[pos] + sorted_data[pos+1]) / 2)
            else:
                quant_list.append(sorted_data[pos])
        return quant_list


class SurveyMedian(SurveyQuantile):
    """
    Derived class from SurveyQuantile with quantile = [.50]
    """
    def __init__(self, SurveyDesign, data, cov_method, mse=False):
        # sp = super(SurveyMedian, self).__init__(SurveyDesign, data, [50])
        sp = SurveyQuantile(SurveyDesign, data, [.50], cov_method, mse)
        self.est = sp.est
        self.vcov = sp.vcov

import numpy as np
from sklearn.linear_model import Lasso, LinearRegression
from sklearn.cluster import FeatureAgglomeration, AgglomerativeClustering
from sklearn.utils import check_random_state
from scipy.stats import pearsonr
import statsmodels.api as sm
from scipy.sparse import coo_matrix, dia_matrix
from sklearn.preprocessing import LabelBinarizer, StandardScaler
from sklearn.linear_model.base import center_data


def projection(X, k, connectivity, ward=True):
    """
    Take the data, and returns a matrix, to reduce the dimension
    Returns, invP, (P.(X.T)).T and the underlying labels
    """
    n, p = X.shape
    if ward:
        clustering = FeatureAgglomeration(
            linkage='ward', n_clusters=k, connectivity=connectivity)
        labels = clustering.fit(X).labels_
    else:
        from fast_cluster import ReNN, recursive_nn
        _, labels = recursive_nn(connectivity, X, n_clusters=k)

    #
    P, P_inv = pp_inv(labels)
    X_proj = P.dot(X.T).T
    # should be done through clustering.transform, but there is an issue
    # with the normalization
    # X_proj = clustering.transform(X)
    return P_inv, X_proj, labels


def pp_inv(clust):
    p = np.size(clust)
    n_labels = len(np.unique(clust))
    parcellation_masks = coo_matrix(
        (np.ones(p), (clust, np.arange(p))),
        shape=(n_labels, p),
        dtype=np.float32).tocsc()
    inv_sum_col = dia_matrix(
        (np.array(1. / parcellation_masks.sum(0)).squeeze(), 0),
        shape=(n_labels, n_labels))

    P_inv = parcellation_masks.copy()
    P_inv = P_inv.T
    P = inv_sum_col * parcellation_masks
    return P, P_inv


def multivariate_split_pval(X, y, n_split, size_split, n_clusters,
                            beta_array, split_array, clust_array):
    """Main function to obtain p-values across splits """
    n, p = X.shape
    pvalues = np.ones((n_split, p))
    for i in range(n_split):
        # perform the split
        split = np.zeros(n, dtype='bool')
        split[split_array[i]] = True
        y_test = y[~split]
        X_test = X[~split]

        # projection
        P, P_inv = pp_inv(clust_array[i])

        # get the support
        beta_proj = beta_array[i]
        model_proj = (beta_proj ** 2 > 0)
        model_proj_size = model_proj.sum()
        X_test_proj = P.dot(X_test.T).T
        X_model = X_test_proj[:, model_proj]

        # fit the model on test data to get p-values
        res = sm.OLS(y_test, X_model).fit()
        pvalues_proj = np.ones(n_clusters)
        pvalues_proj[model_proj] = np.clip(
            model_proj_size * res.pvalues, 0., 1.)
        pvalues[i] = P_inv.dot(pvalues_proj)

    if n_split > 1:
        pvalues_aggregated = pvalues_aggregation(pvalues)
    else:
        pvalues_aggregated = pvalues[0]
    return pvalues, pvalues_aggregated


def multivariate_split_scores(X, y, n_split, size_split, n_clusters,
                              beta_array, split_array, clust_array):
    """Main function to obtain scores across splits """
    n, p = X.shape
    scores = np.ones((n_split, p))
    for i in range(n_split):
        # perform the split
        split = np.zeros(n, dtype='bool')
        split[split_array[i]] = True
        y_test = y[~split]
        X_test = X[~split]

        # projection
        P, P_inv = pp_inv(clust_array[i])

        # get the support
        beta_proj = beta_array[i]
        model_proj = (beta_proj ** 2 > 0)

        beta = P_inv.dot(beta_proj)
        model_size = (beta ** 2 > 0).sum()
        X_test_proj = P.dot(X_test.T).T
        X_model = X_test_proj[:, model_proj]

        # fit the model on test data to get p-values
        res = sm.OLS(y_test, X_model).fit()
        scores_proj = p * np.ones(n_clusters)
        scores_proj[model_proj] = model_size * res.pvalues
        scores[i] = P_inv.dot(scores_proj)

    if n_split > 1:
        scores_aggregated = scores_aggregation(scores)
    else:
        scores_aggregated = scores[0]
    return scores, scores_aggregated


def univariate_split_pval(X, y, n_split, size_split, n_clusters,
                          beta_array, split_array, clust_array,
                          permute=False):
    """Univariate p-values computation
    todo: replace permutations with analytical tests
    """
    n, p = X.shape
    pvalues = np.ones((n_split, p))
    for i in range(n_split):
        split = np.zeros(n, dtype='bool')
        split[split_array[i]] = True
        y_test = y[~split]
        X_test = X[~split]

        # projection
        P, P_inv = pp_inv(clust_array[i])
        X_test_proj = P.dot(X_test.T).T
        X_proj = P.dot(X.T).T

        if permute:
            n_perm = 10000
            corr_true = np.abs(np.dot(y_test, X_test_proj).reshape(
                    (n_clusters)))
            corr_perm = np.zeros((n_perm, n_clusters))
            for s in range(n_perm):
                perm = np.random.permutation(int(n - size_split))
                corr_perm[s] = np.dot(y_test.T, X_test_proj[perm])
            corr_perm = np.abs(corr_perm)
            pvalues_proj = 1. / n_perm * (corr_true < corr_perm).sum(axis=0)
        else:
            #pvalues_proj = np.array([pearsonr(y_test, x)[1]
            #                         for x in X_test_proj.T])
            pvalues_proj = np.array([pearsonr(y, x)[1]
                                     for x in X_proj.T])
        pvalues[i] = P_inv.dot(pvalues_proj)

    pvalues = (pvalues * len(pvalues_proj)).clip(0, 1)
    if n_split > 1:
        pvalues_aggregated = pvalues_aggregation(pvalues)
    else:
        pvalues_aggregated = pvalues[0]
    return pvalues, pvalues_aggregated


def univariate_split_scores(X, y, n_split, size_split, n_clusters,
                           beta_array, split_array, clust_array,
                           permute=False):
    """Univariate p-values computation
    todo: replace permutations with analytical tests
    """
    n, p = X.shape
    scores = np.ones((n_split, p))
    n_perm = 10000
    for i in range(n_split):
        split = np.zeros(n, dtype='bool')
        split[split_array[i]] = True
        y_test = y[~split]
        X_test = X[~split]

        # projection
        P, P_inv = pp_inv(clust_array[i])

        X_test_proj = P.dot(X_test.T).T
        corr_true = np.abs(np.dot(y_test, X_test_proj).reshape(
                (n_clusters)))

        if permute:
            corr_perm = np.zeros((n_perm, n_clusters))
            for s in range(n_perm):
                perm = np.random.permutation(int(n - size_split))
                corr_perm[s] = np.dot(y_test.T, X_test_proj[perm])
            corr_perm = np.abs(corr_perm)
            scores_proj = 1. / n_perm * (corr_true < corr_perm).sum(axis=0)
        else:
            scores_proj = np.array([pearsonr(y_test, x)[1]
                                    for x in X_test_proj.T])
        scores[i, :] = P_inv.dot(scores_proj)

    if n_split > 1:
        pvalues_aggregated = pvalues_aggregation(scores)
    else:
        pvalues_aggregated = scores[0]
    return scores, pvalues_aggregated


def pvalues_aggregation(pvalues, gamma_min=0.05):
    n_split, p = pvalues.shape
    # 
    kmin = max(1, int(gamma_min * n_split))
    pvalues_sorted = np.sort(pvalues, axis=0)[kmin:]
    gamma_array = 1. / n_split * (np.arange(kmin + 1, n_split + 1))
    pvalues_sorted /= gamma_array[:, np.newaxis]
    q = pvalues_sorted.min(axis=0)
    q *= (1 - np.log(gamma_min))
    q = q.clip(0., 1.)
    return q


def scores_aggregation(scores, gamma_min=0.05):
    n_split, p = scores.shape
    kmin = max(1, int(gamma_min * n_split))
    scores_sorted = np.sort(scores, axis=0)[kmin:]
    gamma_array = 1. / n_split * (np.arange(kmin + 1, n_split + 1))
    scores_sorted /= gamma_array[:, np.newaxis]
    q = scores_sorted[0]
    return q


def select_model_fdr(pvalues, q, independent=False, normalize=False):
    """
    Return the model selected by the Benjamini-Hochberg procedure

    pvalues : np.float(p)
              The pvalues of the model

    q : np.float
        The level chosen for the Benjamini-Hochberg procedure

    independent : bool, optional
        Tells if the features variables are independent. If they are not,
        an additional correction is applied (Benjamini-yekutieli)

    normalize : bool, optional
        This option is useful when computing the aggregated p-values
    """
    p, = pvalues.shape
    pvalues_sorted = np.sort(pvalues) / np.arange(1, p + 1)
    if not independent:
        q = q / np.log(p)
    if normalize:
        q = q / p
    if (pvalues_sorted > q).all():
        bound = 0
    else:
        h = np.where(pvalues_sorted <= q)[0][-1]
        bound = pvalues_sorted[h] * (h + 1)
    return pvalues <= bound


def select_model_fdr_bounds(pvalues, independent=False, normalize=True):
    """
    Returns for each feature $i$ the bound $\alpha_i$ such that
    $i$ is selected by a Benjamini-Hochberg procedure of level q
    if an only if $q > \alpha_i$.

    To be more concrete, if 0 < q < 1, and we define : 
    model1 = select_model_fdr(pvalues, q)
    model2 = (select_model_fdr_bounds(pvalues) > q)
    Then model1 = model2
    """
    p, = pvalues.shape
    pvalues_argsort = np.argsort(pvalues)
    pvalues_sorted = pvalues[pvalues_argsort]
    pvalues_sorted = pvalues_sorted / np.arange(1, p + 1)

    bounds_sorted = pvalues_sorted
    for i in range(p - 1, 0, - 1):
        bounds_sorted[i - 1] = min(bounds_sorted[i - 1], bounds_sorted[i])

    bounds = np.zeros(p)
    bounds[pvalues_argsort] = bounds_sorted

    if normalize:
        bounds *= p
    if not independent:
        bounds *= np.log(p)

    bounds = np.clip(bounds, 0., 1.)
    return bounds


def select_model_fwer_bounds(pvalues):
    p, = pvalues.shape
    return np.clip(pvalues * p, 0., 1.)


def test_select_model_fdr_bounds():
    p = 100
    pvalues = np.random.uniform(size=p) ** 5
    bounds = select_model_fdr_bounds(pvalues)
    bounds_sorted = np.sort(bounds)

    print "pvalues : ", pvalues
    print "bounds : ", bounds
    bool_array = np.zeros(1000, dtype=bool)
    for i in range(1000):
        model1 = set(select_model_fdr(pvalues, i / 1000.))
        model2 = set(np.array([j for j in range(p) if bounds[j] <= i / 1000.]))
        bool_array[i] = np.all(model1 == model2)
        if not bool_array[i]:
            print "model1 - model2 : ", model1 - model2
            print "model2 - model1: ", model2 - model1
            #pdb.set_trace()
    return bool_array


class StabilityLasso(LinearRegression):

    alpha = 0.05

    def __init__(self, theta, n_split=100, ratio_split=.5,
                 n_clusters='0.1', model_selection='multivariate',
                 random_state=1):
        """

        Parameters
        ----------
        theta : np.float
            Coefficient factor of the L-1 penalty in
            $\text{minimize}_{\beta} \frac{1}{2} \|y_{splitted}-X_{clustered,split}\beta\|^2_2 + 
                \lambda\|\beta\|_1$
            where $\lambda = \theta \|X_{clustered, split}^Ty_{split}\|_\infty

        n_split : int
            Number of time we randomize the data

        ratio_split : float, optional
            Relative size of the first part (selection). Defaults to .5.

        n_clusters : int
            Number of clusters in the clustering.
            Default is the number of voxels

        connectivity : np.array(p,p)
            Connectivity matrix of the data, used for the spatial clustering

        model_selection: string, optional
        """
        self.theta = theta
        self.n_split = n_split
        self.ratio_split = ratio_split
        self.generator = check_random_state(random_state)
        self.n_clusters = n_clusters

    def fit(self, X, y, connectivity=None, **lasso_args):
        """

        X : np.float((n, p))
            The data, in the model $y = X\beta$

        y : np.float(n)
            The target, in the model $y = X\beta$

        """
        # X, y, X_mean, y_mean, X_std = center_data(
        #    X, y, True, True, True)
        st = StandardScaler()
        y = st.fit_transform(y.reshape(-1, 1))
        self.intercept_ = st.mean_
        X = st.fit_transform(X)

        n, p = X.shape
        n_split = self.n_split
        self.size_split = n * self.ratio_split
        self.n_clusters_ = self.n_clusters
        if isinstance(self.n_clusters, basestring):
            if self.n_clusters_ == 'auto':
                self.n_clusters_ = p
            else:
                self.n_clusters_ = int(eval('%s * p' % self.n_clusters_,
                                        dict(p=p)))
        theta = self.theta

        beta_array = np.zeros((n_split, self.n_clusters_))
        split_array = np.zeros((n_split, self.size_split), dtype=int)
        clust_array = np.zeros((n_split, p), dtype=int)
        self._soln = np.zeros(p)

        for i in range(n_split):
            split = self.generator.choice(n, self.size_split, replace=False)
            split.sort()

            y_splitted, X_splitted = y[split], X[split]
            P_inv, X_proj, labels = projection(
                X_splitted, self.n_clusters_, connectivity)
            alpha = theta * np.max(np.abs(np.dot(X_proj.T, y_splitted))) / n
            lasso_splitted = Lasso(alpha=alpha)
            lasso_splitted.fit(X_proj, y_splitted)
            beta_proj = lasso_splitted.coef_
            beta = P_inv.dot(beta_proj)

            beta_array[i] = beta_proj
            split_array[i] = split
            clust_array[i] = labels
            self._soln += beta

        self._soln /= n_split
        self._beta_array = beta_array
        self._split_array = split_array
        self._clust_array = clust_array
        self.coef_ = self._soln
        return self

    def multivariate_split_pval(self, X, y):
        pvalues, pvalues_aggregated = multivariate_split_pval(
            X, y, self.n_split, self.size_split, self.n_clusters_,
            self._beta_array, self._split_array, self._clust_array)
        self._pvalues = pvalues
        self._pvalues_aggregated = pvalues_aggregated
        return pvalues_aggregated

    def multivariate_split_scores(self, X, y):
        scores, scores_aggregated = multivariate_split_scores(
            X, y, self.n_split, self.size_split, self.n_clusters_,
            self._beta_array, self._split_array, self._clust_array)
        self._scores = scores
        self._scores_aggregated = scores_aggregated
        return scores_aggregated

    def univariate_split_pval(self, X, y):
        pvalues, pvalues_aggregated = univariate_split_pval(
            X, y, self.n_split, self.size_split, self.n_clusters_,
            self._beta_array, self._split_array, self._clust_array)
        self._pvalues = pvalues
        self._pvalues_aggregated = pvalues_aggregated
        return pvalues_aggregated

    def select_model_fwer(self, alpha):
        p, = self._pvalues_aggregated.shape
        return self._pvalues_aggregated < (alpha / p)

    def select_model_fdr(self, q, normalize=True):
        return select_model_fdr(self._pvalues_aggregated, q,
                                normalize=normalize)

    def select_model_fdr_bounds_scores(self, normalize=False):
        return select_model_fdr_bounds(self._scores_aggregated,
                                       normalize=normalize)

    def select_model_fdr_scores(self, q, normalize=True):
        return select_model_fdr(self._scores_aggregated, q,
                                normalize=normalize)

    @property
    def classes_(self):
        return self._label_binarizer.classes_



import numpy as np
from scipy.sparse import coo_matrix
import matplotlib.pyplot as plt

from stab_lasso import StabilityLasso, select_model_fdr
from sklearn.metrics import roc_curve, precision_recall_curve
from scipy.stats import pearsonr
from joblib import Parallel, delayed

from plot_simulated_data import (univariate_simulation, plot_slices, plot_row_slices,
                                 multivariate_simulation)

SHAPE = (12, 12, 12)


def connectivity(shape):
    from sklearn.feature_extraction import image
    connectivity = image.grid_to_graph(n_x=shape[0], n_y=shape[1],
                                       n_z=shape[2])
    return connectivity


def pedagogical_example(shape=SHAPE, n_samples=100, split_ratio=.3, n_split=20,
                        random_seed=1, modulation=False, snr=0,
                        mean_size_clust=10, alpha=.05, theta=.1):
    """Create a simple minded example with plots to figure it out"""
    coefs = {}
    size = np.prod(shape)
    k = int(size / mean_size_clust)

    X, y, snr, noise, beta0, _ = \
        multivariate_simulation(snr, n_samples, shape, random_seed,
                               modulation=modulation)
    coefs['true'] = np.reshape(beta0 * 10, shape)

    # Start with an ANOVA
    pvals = np.array([pearsonr(y, x)[1] for x in X.T])
    anova_model = select_model_fdr(pvals, alpha)
    coefs['anova'] = np.reshape(- np.log(
            (pvals * len(anova_model)).clip(0, 1)) * anova_model, shape)
    connectivity_ = connectivity(shape)
    for model_selection in ['univariate', 'multivariate', 'scores']:
        # run the stablasso
        stability_lasso = StabilityLasso(
            theta, n_split=n_split, ratio_split=split_ratio,
            n_clusters=k, model_selection=model_selection)
        stability_lasso.fit(X, y, connectivity_)
        if model_selection is 'univariate':
            pvals = stability_lasso.univariate_split_pval(X, y)
        else:
            pvals = stability_lasso.multivariate_split_pval(X, y)
        selected_model = stability_lasso.select_model_fdr(alpha, normalize=False)
        coefs[model_selection] = np.reshape(-np.log(pvals) * selected_model,
                                             shape)
    plot_row_slices(coefs)
    plt.show()


def stat_test(model_selection='multivariate',
              control_type='pvals',
              plot=False,
              print_results=True,
              n_samples=100,
              n_split=1,
              split_ratio=.4,
              mean_size_clust=1,
              theta=0.1,
              snr=-10,
              random_seed=1,
              alpha=.2,
              shape=SHAPE):

    size = np.prod(shape)
    k = int(size / mean_size_clust)

    X, y, snr, noise, beta0, _ = \
        univariate_simulation(snr, n_samples, shape, random_seed,
                              modulation=True)
    true_coeff = beta0 ** 2 > 0

    if model_selection == 'anova':
        pvals = np.array([pearsonr(y, x)[1] for x in X.T])
        selected_model = select_model_fdr(pvals, alpha)
        false_discovery = selected_model * (~true_coeff)
        true_discovery = selected_model * true_coeff
        undiscovered = true_coeff.sum() - true_discovery.sum()
        fdr = (float(false_discovery.sum()) /
               max(1., float(selected_model.sum())))
        recall = float(true_discovery.sum()) / np.sum(true_coeff)
        return fdr, recall, pvals, pvals, true_coeff

    connectivity_ = connectivity(shape)
    stability_lasso = StabilityLasso(
        theta, n_split=n_split, ratio_split=split_ratio,
        n_clusters=k, model_selection=model_selection)

    stability_lasso.fit(X, y, connectivity_)
    beta = stability_lasso._soln

    if model_selection == 'univariate':
        pvals = stability_lasso.univariate_split_pval(X, y)
        scores = pvals
        selected_model = stability_lasso.select_model_fdr(alpha)
    elif model_selection == 'multivariate':
        pvals = stability_lasso.multivariate_split_pval(X, y)
        scores = stability_lasso.multivariate_split_scores(X, y)
        if control_type == 'pvals':
            selected_model = stability_lasso.select_model_fdr(
                alpha, normalize=False)
        elif control_type == 'scores':
            selected_model = stability_lasso.select_model_fdr_scores(
                alpha, normalize=False)
    else:
        raise ValueError("This model selection method doesn't exist")

    beta_corrected = np.zeros(size)
    if len(selected_model) > 0:
        beta_corrected[selected_model] = beta[selected_model]
        false_discovery = selected_model * (~true_coeff)
        true_discovery = selected_model * true_coeff
    else:
        false_discovery = np.array([])
        true_discovery  = np.array([])

    undiscovered = true_coeff.sum() - true_discovery.sum()

    fdr = (float(false_discovery.sum()) /
           max(1., float(selected_model.sum())))

    recall = float(true_discovery.sum()) / np.sum(true_coeff)

    if print_results:
        print("------------------- RESULTS -------------------")
        print("-----------------------------------------------")
        print("FDR : ", fdr)
        print("DISCOVERED FEATURES : ", true_discovery.sum())
        print("UNDISCOVERED FEATURES : ", undiscovered)
        print("-----------------------------------------------")
        print("TRUE DISCOVERY")
        print("| Feature ID |       p-value      |")
        for i in range(size):
            if true_discovery[i]:
                print("|   " + str(i).zfill(4) + "   |  "+str(pvals[i]) + "  |")
        print("-----------------------------------------------")
        print("FALSE DISCOVERY")
        print("| Feature ID |       p-value      |")
        for i in range(size):
            if false_discovery[i]:
                print("|   " + str(i).zfill(4) + "   |  "+str(pvals[i]) + "  |")
        print("-----------------------------------------------")
    if plot:
        coef_est = np.reshape(beta_corrected, shape)
        plot_slices(coef_est, title="Estimated")
        plot_slices(np.reshape(true_coeff, shape), title="Ground truth")
        plt.show()

    return fdr, recall, pvals, scores, true_coeff


def multiple_test(n_test,
                  model_selection='multivariate',
                  control_type='pvals',
                  n_samples=100,
                  n_split=30,
                  split_ratio=.5,
                  mean_size_clust=1,
                  theta=0.1,
                  snr=-10,
                  rs_start=1,
                  plot=False,
                  alpha=.05,
                  shape=SHAPE):
    """Runs several tests and accumulate results

    Parameters
    ----------
    n_test: int,
            The number of tests to run

    model_selection: string, optional
            the statistical etst performed at validation time
            one of 'multivariate' (default), 'univariate' or 'anova'
            'Anova' refers to standard univariate screening as opposed to
            high-dimensional regression

    control_type: string, optional,
            one of 'pvals', 'scores'
            FIXME: clarify semantics

    n_samples: int, optional,
            number of samples used in the simulations

    n_split: int, optional,
           number of splits in the bagging part of the method

    split_ratio: float, optional
            int the [0, 1] interval. Proportion of samples used for screening

    mean_size_clust: int, optional,
            Average cluster size when clustering is used.
            Used to decide the number of clusters

    theta: float, optional,
           Regularization parameter. FIXME: check

    snr: float, optional,
         Signal to noise ration (in dB) of the simulated effect

    rs_start: int, optional,
              seed of rng for simulations. FIXME: check

    plot: Bool, optional,
          whether to plot the ROC/PR curves or not

    alpha: float, optional
           Desired fdr / Type 1 error rate

    shape: tuple of int, optional,
          shape of the data volume
    """
    fdr_array = []
    recall_array = []
    pvals = []
    scores = []
    true_coeffs = []

    for i in range(n_test):
        fdr, recall, pval, score, true_coeff = stat_test(
            model_selection=model_selection,
            control_type=control_type,
            n_samples=n_samples,
            n_split=n_split,
            split_ratio=split_ratio,
            mean_size_clust=mean_size_clust,
            theta=theta,
            snr=snr,
            random_seed=rs_start + i,
            print_results=False,
            plot=plot,
            alpha=alpha,
            shape=shape)
        fdr_array.append(fdr)
        recall_array.append(recall)
        pvals.append(pval)
        scores.append(score)
        true_coeffs.append(true_coeff)

    return np.array(fdr_array), np.array(recall_array)


def experiment_nominal_control(control_type='scores', n_splits=[20],
                               clust_sizes=[1], n_test=20):
    """This experiments checks empirically type I error rate/fdr"""
    for n_split in n_splits:
        for mean_size_clust in clust_sizes:
            for model_selection in ['univariate', 'multivariate']:
                fdr_array, recall_array = multiple_test(
                    model_selection=model_selection, control_type='scores',
                    n_test=n_test, n_split=n_split,
                    mean_size_clust=mean_size_clust,
                    split_ratio=.5, plot=False, alpha=1., theta=.9, snr=-10)
                print('model selection %s cluster_size %d, n_split %d' % (
                        model_selection, mean_size_clust, n_split))
                print('average fdr: %0.3f' % np.mean(fdr_array))
                print('average recall: %0.3f' % np.mean(recall_array))
                print('fwer: %0.3f' % np.mean(fdr_array > 0))


def experiment_roc_curve(model_selection='multivariate', roc_type='scores'):
    # set various parameters
    n_samples = 100
    n_test = 20
    split_ratio = .4
    theta = 0.8
    snr = - 10
    rs_start = 1

    ax = plt.subplot(111)
    for n_split in [1, 20]:
        for mean_size_clust in [1, 5, 10]:
            # fdr, recall, pval, score, true_coeff
            res = Parallel(n_jobs=1)(
                delayed(stat_test)(model_selection=model_selection,
                              n_samples=n_samples,
                              n_split=n_split,
                              split_ratio=split_ratio,
                              mean_size_clust=mean_size_clust,
                              theta=theta,
                              snr=snr,
                              random_seed=rs_start + i,
                              print_results=False,
                              plot=False) for i in range(n_test))
            pvals = [res_[2] for res_ in res]
            scores = [res_[3] for res_ in res]
            true_coeffs = [res_[4] for res_ in res]
            n_clusters = pvals[0].size / mean_size_clust

            if roc_type == 'pvals':
                fpr, tpr, thresholds = roc_curve(
                    np.concatenate(true_coeffs, 1),
                    1 - np.concatenate(pvals, 1))
            elif roc_type == 'scores':
                fpr, tpr, thresholds = roc_curve(
                    np.concatenate(true_coeffs, 1).ravel(),
                    true_coeffs[0].size - np.concatenate(scores))
            elif roc_type == 'pr':
                fpr, tpr, _ = precision_recall_curve(
                    np.concatenate(true_coeffs, 1).ravel(),
                    true_coeffs[0].size - np.concatenate(scores))
            linewidth = 1
            if model_selection == 'multivariate':
                linewidth = 2
            ax.plot(fpr, tpr, label='n_split=%d, %d clusters' % (
                    n_split, n_clusters), linewidth=linewidth)
    ax.plot([0, 1], [0, 1], 'k--')
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.legend(loc=4)
    ax.set_title('ROC curves. split ratio = %1.1f' % split_ratio)


def anova_curve(roc_type='scores'):
    # set various parameters
    n_samples = 100
    n_test = 20
    snr = - 10
    rs_start = 1

    ax = plt.subplot(111)
    # collect results
    pvals = []
    scores = []
    true_coeffs = []
    for i in range(n_test):
        fdr, recall, pval, score, true_coeff = stat_test(
            model_selection='anova',
            n_samples=n_samples,
            snr=snr,
            random_seed=rs_start + i,
            print_results=False,
            plot=False)
        pvals.append(pval)
        scores.append(score)
        true_coeffs.append(true_coeff.ravel())

    curve = roc_curve if roc_type == 'scores' else precision_recall_curve
    fpr, tpr, _ = curve(
        np.concatenate(true_coeffs), 1 - np.concatenate(pvals))
    ax.plot(fpr, tpr, '--', label='anova')
    ax.plot([0, 1], [0, 1], 'k--')
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.legend(loc=4)


if __name__ == '__main__':
    pedagogical_example()
    """
    experiment_nominal_control(control_type='scores', clust_sizes=[1])
    anova_curve()
    experiment_roc_curve('univariate')
    experiment_roc_curve('multivariate')
    plt.savefig('roc_curves.png')
    plt.show()
    """

# PROBEER OOIT NOG EEN KEER OM DE countvec OP MAX TE ZETTEN OFZO
# https://github.com/paulgb/sklearn-pandas

# from sklearn.decomposition import PCA
import copy

import numpy as np
import pandas as pd
import scipy.sparse

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import OneHotEncoder, robust_scale
from dateutil.parser import parse
from xtoy.utils import is_numeric
from xtoy.utils import is_integer

from xtoy.featurizers import SelectPolynomialByResidual
from xtoy.featurizers import RegexVectorizer


class DataFrameImputer(TransformerMixin):
    """
    Credits http://stackoverflow.com/a/25562948/1575066
    """

    def __init__(self):
        """Impute missing values.

        Columns of dtype object are imputed with the most frequent value
        in column.

        Columns of other types are imputed with mean of column.

        """
        self.fill = None

    @staticmethod
    def most_frequent(col):
        try:
            return col.value_counts().index[0]
        except IndexError:
            return 0

    def get_impute_val(self, col):
        if col.dtype == np.dtype('O'):
            val = self.most_frequent(col)
        elif col.dtype == np.dtype(float):
            val = col.mean()
        else:
            val = col.median()
        if isinstance(val, float) and np.isnan(val):
            val = 0
        return val

    def fit(self, X, y=None):
        self.fill = pd.Series([self.get_impute_val(X[c]) for c in X], index=X.columns)
        return self

    def transform(self, X, y=None):
        return X.fillna(self.fill, inplace=False)


class Sparsify(BaseEstimator, TransformerMixin):

    def __init__(self,
                 count_vectorizer=CountVectorizer(max_features=15, token_pattern=r"(?u)\b\w+\b"),
                 max_unique_for_discrete=15,
                 date_atts=("year", "month", "day", "weekday", "hour", "minute", "second"),
                 regex_vectorizer=None,
                 regex_patterns=None):
        self.count_vectorizer = count_vectorizer
        self.regex_vectorizer = regex_vectorizer or RegexVectorizer(
            regex_patterns) if regex_patterns else None
        self.max_unique_for_discrete = max_unique_for_discrete
        self.one_hot_encoder = None
        # scary duplication
        self.drop_vars = []
        self.count_vecs = []
        self.regex_vecs = []
        self.date_vars = []
        self.imputer = DataFrameImputer()
        self.ohe_indices = []
        self.numeric_indices = []
        self.missing_col_names = []
        self.var_names_ = None
        self.date_atts = date_atts

    def fit(self, X, y=None):
        if not isinstance(X, pd.DataFrame):
            X = pd.DataFrame(X)
        self.var_names_ = []
        for col_name in X.columns[np.any(pd.isnull(X), axis=0)]:
            self.var_names_.append(str(col_name) + "_missing")
            self.missing_col_names.append(col_name)
        X = self.imputer.fit_transform(X)
        self.ohe_indices = np.zeros(X.shape[1], dtype=bool)
        self.numeric_indices = np.zeros(X.shape[1], dtype=bool)
        self.drop_vars = np.zeros(X.shape[1], dtype=bool)
        self.date_vars = np.zeros(X.shape[1], dtype=bool)
        for i, col in enumerate(X):
            if len(set(X[col])) == 1:
                self.drop_vars[i] = True

        for i, col in enumerate(X):
            if self.drop_vars[i]:
                continue
            if is_numeric(X[col]):
                if len(set(X[col])) > 2:
                    self.var_names_.append('{}_{}_continuous'.format(col, i))
                else:
                    self.var_names_.append('{}_{}_dummy'.format(col, i))
                num_unique = len(np.unique(X[col]))
                if is_integer(X[col]) and 3 <= num_unique <= self.max_unique_for_discrete:
                    self.ohe_indices[i] = True
                self.numeric_indices[i] = True
            # maybe date
            else:
                for x in X[col]:
                    try:
                        parse(x)
                    except ValueError:
                        break
                else:
                    self.date_vars[i] = True
                    date_var_names = ['{}_date_{}'.format(col, x)
                                      for j, x in enumerate(self.date_atts)]
                    self.var_names_.extend(date_var_names)

        for i, (ohed, col) in enumerate(zip(self.ohe_indices, X)):
            if (self.count_vectorizer and not self.drop_vars[i] and not is_numeric(X[col]) and
                    not ohed and not self.date_vars[i]):
                countvec = copy.copy(self.count_vectorizer)
                countvec.fit(['' if isinstance(x, float) else x for x in X[col]])
                self.count_vecs.append(countvec)
                cv_var_names = ['{}_countvec_{}_{}_{}'.format(col, x, i, j)
                                for j, x in enumerate(countvec.get_feature_names())]
                self.var_names_.extend(cv_var_names)
            else:
                self.count_vecs.append(False)

        for i, (ohed, col) in enumerate(zip(self.ohe_indices, X)):
            if (self.regex_vectorizer and not self.drop_vars[i] and not is_numeric(X[col]) and
                    not ohed and not self.date_vars[i]):
                regex_vec = copy.copy(self.regex_vectorizer)
                regex_vec.dict_vectorizer = DictVectorizer(
                    **self.regex_vectorizer.dict_vectorizer.get_params())
                regex_vec.fit(['' if isinstance(x, float) else x for x in X[col]])
                if regex_vec.get_feature_names():
                    self.regex_vecs.append(regex_vec)
                    rv_var_names = ['{}_regex_vec_{}_{}_{}'.format(col, x, i, j)
                                    for j, x in enumerate(regex_vec.get_feature_names())]
                    self.var_names_.extend(rv_var_names)
                else:
                    self.regex_vecs.append(False)
            else:
                self.regex_vecs.append(False)

        self.one_hot_encoder = OneHotEncoder(handle_unknown='ignore')
        if np.any(self.ohe_indices):
            self.one_hot_encoder.fit(X[X.columns[self.ohe_indices]])
            # ridiculously complex OHE feature range names
            feat = set(self.one_hot_encoder.active_features_)
            for l, h, v in zip(self.one_hot_encoder.feature_indices_[:-1],
                               self.one_hot_encoder.feature_indices_[1:],
                               X.columns[self.ohe_indices]):
                self.var_names_.extend(['{}_OHE_{}'.format(v, j)
                                        for j in range(len(feat.intersection(range(l, h))))])
        self.var_names_ = np.array(self.var_names_)
        return self

    def transform(self, X, y=None):
        if not isinstance(X, pd.DataFrame):
            X = pd.DataFrame(X)
        res = []
        cvs = []
        rvs = []
        date_groups = []
        for col in self.missing_col_names:
            res.append(pd.isnull(X[col]))
        X = self.imputer.transform(X)
        for i, col in enumerate(X):
            if self.drop_vars[i] or self.count_vecs[i]:
                continue
            if self.numeric_indices[i]:
                res.append(X[col])
            elif not self.ohe_indices[i] and self.date_vars[i]:
                prefix = str(col) + "__"
                dtimes = [parse(x) for x in X[col]]
                for a in self.date_atts:
                    dcol = [x.weekday() if a == "weekday" else getattr(x, a) for x in dtimes]
                    res.append(dcol)

        for cv, col in zip(self.count_vecs, X):
            if cv:
                cvs.append(cv.transform(['' if isinstance(x, (np.int64, int, float)) else x
                                         for x in X[col]]))

        for rv, col in zip(self.regex_vecs, X):
            if rv:
                rvs.append(rv.transform(['' if isinstance(x, (np.int64, int, float)) else x
                                         for x in X[col]]))

        combined = []
        if res:
            combined.append(scipy.sparse.coo_matrix(res).T)
        if cvs:
            combined.extend(cvs)

        if rvs:
            combined.extend(rvs)
        if np.any(self.ohe_indices):
            ohd = self.one_hot_encoder.transform(X[X.columns[self.ohe_indices]])
            combined = combined + [ohd]

        return scipy.sparse.hstack(combined).tocsr()


# for k in train:
#     s = Sparsify()
#     XX = s.fit_transform(train[k])
#     assert len(s.var_names_) == XX.shape[1]


# feature_important = pd.DataFrame(index=np.array(
#     s.var_names_)[rfe.support_], data=clf.feature_importances_, columns=['importance'])
# feature_important = feature_important.sort_values(by=['importance'], ascending=True)
# feature_important.plot(kind='barh', stacked=True, color=[
#                        'cornflowerblue'], grid=False, figsize=(8, 5))


# import copy
# s = Sparsify()
# XX = s.fit_transform(train[::2])
# XX2 = s.transform(train[1::2])

# from sklearn.feature_selection import RFE

# rfe = RFE(LogisticRegression(), n_features_to_select=100, step=0.1)
# XX = rfe.fit_transform(XX, y[0::2])
# XX2 = rfe.transform(XX2)


# preds = []
# for clf in [RandomForestClassifier(1000, n_jobs=4),
#             MLPClassifier((100, 100)),
#             MLPClassifier((100, 100)),
#             KNeighborsClassifier(),
#             LogisticRegression()]:
#     clf.fit(XX, y[::2])
#     print(clf)
#     pred = clf.predict(XX2)
#     print(np.mean(pred == y[1::2]))
#     preds.append(pred)
#     clfs.append(clf)

# from scipy.stats import mode
# np.mean(mode(preds)[0].ravel() == y[1::2])

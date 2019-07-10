import time
from operator import itemgetter
import numpy as np
from ..evaluate import rmse, MAP_at_k, accuracy
from ..utils.initializers import truncated_normal
try:
    import tensorflow as tf
except ModuleNotFoundError:
    print("you need tensorflow for tf-version of this model")


class ALS_rating:
    def __init__(self, n_factors=100, n_epochs=20, reg=5.0, task="rating", seed=42):
        self.n_factors = n_factors
        self.n_epochs = n_epochs
        self.reg = reg
        self.task = task
        self.seed = seed

    def fit(self, dataset, verbose=1):
        np.random.seed(self.seed)
        self.dataset = dataset
        self.default_prediction = dataset.global_mean
        self.pu = truncated_normal(shape=(dataset.n_users, self.n_factors),
                                   mean=0.0, scale=0.05)
        self.qi = truncated_normal(shape=(dataset.n_items, self.n_factors),
                                   mean=0.0, scale=0.05)

        for epoch in range(1, self.n_epochs + 1):
            t0 = time.time()
            for u in dataset.train_user:
                u_items = np.array(list(dataset.train_user[u].keys()))
                u_labels = np.array(list(dataset.train_user[u].values()))
                u_labels_expand = np.expand_dims(u_labels, axis=1)
                yy_reg = self.qi[u_items].T.dot(self.qi[u_items]) + \
                         self.reg * np.eye(self.n_factors)
                r_y = np.sum(np.multiply(u_labels_expand, self.qi[u_items]), axis=0)
                self.pu[u] = np.linalg.inv(yy_reg).dot(r_y)

            for i in dataset.train_item:
                i_users = np.array(list(dataset.train_item[i].keys()))
                i_labels = np.array(list(dataset.train_item[i].values()))
                i_labels_expand = np.expand_dims(i_labels, axis=1)
                xx_reg = self.pu[i_users].T.dot(self.pu[i_users]) + \
                         self.reg * np.eye(self.n_factors)
                r_x = np.sum(np.multiply(i_labels_expand, self.pu[i_users]), axis=0)
                self.qi[i] = np.linalg.inv(xx_reg).dot(r_x)

            if verbose > 0 and epoch % 5 == 0 and self.task == "rating":
                print("Epoch {} time: {:.4f}".format(epoch, time.time() - t0))
                print("training rmse: ", rmse(self, dataset, "train"))
                print("test rmse: ", rmse(self, dataset, "test"))
            elif verbose > 0 and epoch % 5 == 0 and self.task == "ranking":
                print("Epoch {} time: {:.4f}".format(epoch, time.time() - t0))
                print("MAP@{}: {:.4f}".format(5, MAP_at_k(self, dataset, 5)))

        return self

    def predict(self, u, i):
        try:
            pred = np.dot(self.pu[u], self.qi[i])
            pred = np.clip(pred, 1, 5)
        except IndexError:
            pred = self.default_prediction
        return pred

    def recommend_user(self, u, n_rec, random_rec=False):
        unlabled_items = list(set(range(self.dataset.n_items)) - set(self.dataset.train_user[u]))
        if np.any(np.array(unlabled_items) > self.dataset.n_items):
            rank = [(j, self.predict(u, j)) for j in range(len(self.qi))
                    if j not in self.dataset.train_user[u]]
        else:
            pred = np.dot(self.pu[u], self.qi[unlabled_items].T)
            pred = np.clip(pred, 1, 5)
            rank = list(zip(unlabled_items, pred))

        if random_rec:
            item_pred_dict = {j: r for j, r in rank if r >= 4}
            item_list = list(item_pred_dict.keys())
            pred_list = list(item_pred_dict.values())
            p = [p / np.sum(pred_list) for p in pred_list]
            item_candidates = np.random.choice(item_list, n_rec, replace=False, p=p)
            reco = [(item, item_pred_dict[item]) for item in item_candidates]
            return reco
        else:
            rank.sort(key=itemgetter(1), reverse=True)
            return rank[:n_rec]


class ALS:
    def __init__(self, n_factors=100, n_epochs=20, reg=5.0, task="rating", seed=42):
        self.n_factors = n_factors
        self.n_epochs = n_epochs
        self.reg = reg
        self.task = task
        self.seed = seed

    def fit(self, dataset, verbose=1):
        np.random.seed(self.seed)
        self.dataset = dataset
        self.default_prediction = dataset.global_mean
        self.pu = truncated_normal(shape=(dataset.n_users, self.n_factors),
                                   mean=0.0, scale=0.05)
        self.qi = truncated_normal(shape=(dataset.n_items, self.n_factors),
                                   mean=0.0, scale=0.05)

        for epoch in range(1, self.n_epochs + 1):
            t0 = time.time()
            for u in dataset.train_user:
                u_items = dataset.train_item_implicit[np.where(dataset.train_user_implicit == u)]
                u_labels = dataset.train_label_implicit[np.where(dataset.train_user_implicit == u)]
                u_labels_expand = np.expand_dims(u_labels, axis=1)
                yy_reg = self.qi[u_items].T.dot(self.qi[u_items]) + \
                         self.reg * np.eye(self.n_factors)
                r_y = np.sum(np.multiply(u_labels_expand, self.qi[u_items]), axis=0)
                self.pu[u] = np.linalg.inv(yy_reg).dot(r_y)

            for i in dataset.train_item:
                i_users = dataset.train_user_implicit[np.where(dataset.train_item_implicit == i)]
                i_labels = dataset.train_label_implicit[np.where(dataset.train_item_implicit == i)]
                i_labels_expand = np.expand_dims(i_labels, axis=1)
                xx_reg = self.pu[i_users].T.dot(self.pu[i_users]) + \
                         self.reg * np.eye(self.n_factors)
                r_x = np.sum(np.multiply(i_labels_expand, self.pu[i_users]), axis=0)
                self.qi[i] = np.linalg.inv(xx_reg).dot(r_x)

            if verbose > 0 and epoch % 1 == 0 and self.task == "rating":
                print("Epoch {} time: {:.4f}".format(epoch, time.time() - t0))
                print("training rmse: ", rmse(self, dataset, "train"))
                print("test rmse: ", rmse(self, dataset, "test"))
            elif verbose > 0 and epoch % 1 == 0 and self.task == "ranking":
                print("Epoch {} time: {:.4f}".format(epoch, time.time() - t0))
            #    print("MAP@{}: {:.4f}".format(5, MAP_at_k(self, dataset, 5)))
                print("training accuracy: ", accuracy(self, dataset, "train"))
                print("test accuracy: ", accuracy(self, dataset, "test"))

        return self

    def predict(self, u, i):
        try:
            prob = 1 / (1 + np.exp(-np.dot(self.pu[u], self.qi[i])))
            pred = 1.0 if prob >= 0.5 else 0.0
        except IndexError:
            pred = self.default_prediction
        return pred

    def recommend_user(self, u, n_rec, random_rec=False):
        unlabled_items = list(set(range(self.dataset.n_items)) - set(self.dataset.train_user[u]))
        if np.any(np.array(unlabled_items) > self.dataset.n_items):
            rank = [(j, self.predict(u, j)) for j in range(len(self.qi))
                    if j not in self.dataset.train_user[u]]
        else:
            pred = np.dot(self.pu[u], self.qi[unlabled_items].T)
            pred = np.clip(pred, 1, 5)
            rank = list(zip(unlabled_items, pred))

        if random_rec:
            item_pred_dict = {j: r for j, r in rank if r >= 4}
            item_list = list(item_pred_dict.keys())
            pred_list = list(item_pred_dict.values())
            p = [p / np.sum(pred_list) for p in pred_list]
            item_candidates = np.random.choice(item_list, n_rec, replace=False, p=p)
            reco = [(item, item_pred_dict[item]) for item in item_candidates]
            return reco
        else:
            rank.sort(key=itemgetter(1), reverse=True)
            return rank[:n_rec]
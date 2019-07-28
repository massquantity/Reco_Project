"""

Reference: Xiangnan He et al. "Neural Collaborative Filtering"  (https://arxiv.org/pdf/1708.05031.pdf)

author: massquantity

"""
import time
import itertools
import numpy as np
import tensorflow as tf
from ..utils.sampling import NegativeSampling
from ..evaluate.evaluate import precision_tf, MAP_at_k, MAR_at_k, HitRatio_at_k, NDCG_at_k


class NCF:
    def __init__(self, embed_size, lr, n_epochs=20, reg=0.0,
                 batch_size=64, dropout_rate=0.0, seed=42, task="rating"):
        self.embed_size = embed_size
        self.lr = lr
        self.n_epochs = n_epochs
        self.reg = reg
        self.batch_size = batch_size
        self.dropout_rate = dropout_rate
        self.seed = seed
        self.task = task

    def build_model(self, dataset):
        tf.set_random_seed(self.seed)
        self.dataset = dataset
        self.n_users = dataset.n_users
        self.n_items = dataset.n_items
        self.global_mean = dataset.global_mean
        regularizer = tf.contrib.layers.l2_regularizer(self.reg)
        #    self.pu_GMF = tf.get_variable(name="pu_GMF", initializer=tf.glorot_normal_initializer().__call__(shape=[2,2]))
        self.pu_GMF = tf.get_variable(name="pu_GMF", initializer=tf.variance_scaling_initializer,
                                      regularizer=regularizer,
                                      shape=[self.n_users, self.embed_size])
        self.qi_GMF = tf.get_variable(name="qi_GMF", initializer=tf.variance_scaling_initializer,
                                      regularizer=regularizer,
                                      shape=[self.n_items, self.embed_size])
        self.pu_MLP = tf.get_variable(name="pu_MLP", initializer=tf.variance_scaling_initializer,
                                      regularizer=regularizer,
                                      shape=[self.n_users, self.embed_size])
        self.qi_MLP = tf.get_variable(name="qi_MLP", initializer=tf.variance_scaling_initializer,
                                      regularizer=regularizer,
                                      shape=[self.n_items, self.embed_size])

        self.user_indices = tf.placeholder(tf.int32, shape=[None], name="user_indices")
        self.item_indices = tf.placeholder(tf.int32, shape=[None], name="item_indices")
        self.labels = tf.placeholder(tf.float32, shape=[None], name="labels")

        self.pu_GMF_embedding = tf.nn.embedding_lookup(self.pu_GMF, self.user_indices)
        self.qi_GMF_embedding = tf.nn.embedding_lookup(self.qi_GMF, self.item_indices)
        self.pu_MLP_embedding = tf.nn.embedding_lookup(self.pu_MLP, self.user_indices)
        self.qi_MLP_embedding = tf.nn.embedding_lookup(self.qi_MLP, self.item_indices)

        self.GMF_layer = tf.multiply(self.pu_GMF_embedding, self.qi_GMF_embedding)

        self.MLP_input = tf.concat([self.pu_MLP_embedding, self.qi_MLP_embedding], axis=1, name="MLP_input")
        self.MLP_layer1 = tf.layers.dense(inputs=self.MLP_input,
                                          units=self.embed_size * 2,
                                          activation=tf.nn.relu,
        #                                  kernel_initializer=tf.variance_scaling_initializer,
                                          name="MLP_layer1")
        self.MLP_layer1 = tf.layers.dropout(self.MLP_layer1, rate=self.dropout_rate)
        self.MLP_layer2 = tf.layers.dense(inputs=self.MLP_layer1,
                                          units=self.embed_size,
                                          activation=tf.nn.relu,
        #                                  kernel_initializer=tf.variance_scaling_initializer,
                                          name="MLP_layer2")
        self.MLP_layer2 = tf.layers.dropout(self.MLP_layer2, rate=self.dropout_rate)
        self.MLP_layer3 = tf.layers.dense(inputs=self.MLP_layer2,
                                          units=self.embed_size,
                                          activation=tf.nn.relu,
        #                                  kernel_initializer=tf.variance_scaling_initializer,
                                          name="MLP_layer3")

        self.Neu_layer = tf.concat([self.GMF_layer, self.MLP_layer3], axis=1)

        if self.task == "rating":
            self.pred = tf.layers.dense(inputs=self.Neu_layer, units=1, name="pred")
            #    self.loss = tf.reduce_sum(tf.square(tf.cast(self.labels, tf.float32) - self.pred)) / \
            #                tf.cast(tf.size(self.labels), tf.float32)
            self.loss = tf.losses.mean_squared_error(labels=tf.reshape(self.labels, [-1, 1]), predictions=self.pred)
            self.rmse = tf.sqrt(
                tf.losses.mean_squared_error(labels=tf.reshape(self.labels, [-1, 1]),
                                             predictions=tf.clip_by_value(self.pred, 1, 5)))

        elif self.task == "ranking":
            self.logits = tf.layers.dense(inputs=self.Neu_layer, units=1, name="logits")
            self.logits = tf.reshape(self.logits, [-1])
            self.loss = tf.reduce_mean(
                tf.nn.sigmoid_cross_entropy_with_logits(labels=self.labels, logits=self.logits))

            self.y_prob = tf.sigmoid(self.logits)
            self.pred = tf.where(self.y_prob >= 0.5,
                                 tf.fill(tf.shape(self.logits), 1.0),
                                 tf.fill(tf.shape(self.logits), 0.0))

            self.accuracy = tf.reduce_mean(tf.cast(tf.equal(self.pred, self.labels), tf.float32))
            self.precision = precision_tf(self.pred, self.labels)

    def fit(self, dataset, verbose=1):
        self.build_model(dataset)
        self.optimizer = tf.train.AdamOptimizer(self.lr)
    #    self.optimizer = tf.train.FtrlOptimizer(learning_rate=0.1, l1_regularization_strength=1e-3)
        self.training_op = self.optimizer.minimize(self.loss)
        init = tf.global_variables_initializer()

        self.sess = tf.Session()
        self.sess.run(init)
        with self.sess.as_default():
            if self.task == "rating":
                for epoch in range(1, self.n_epochs + 1):
                    t0 = time.time()
                    n_batches = len(dataset.train_labels) // self.batch_size
                    for n in range(n_batches):
                        end = min(len(dataset.train_labels), (n+1) * self.batch_size)
                        u = dataset.train_user_indices[n * self.batch_size: end]
                        i = dataset.train_item_indices[n * self.batch_size: end]
                        r = dataset.train_labels[n * self.batch_size: end]
                        self.sess.run([self.training_op],
                                  feed_dict={self.user_indices: u,
                                             self.item_indices: i,
                                             self.labels: r})

                    if verbose > 0:
                        test_rmse = self.sess.run(self.rmse,
                                                  feed_dict={self.user_indices: dataset.test_user_indices,
                                                             self.item_indices: dataset.test_item_indices,
                                                             self.labels: dataset.test_labels})
                        print("Epoch {}, training time: {:.2f}".format(epoch, time.time() - t0))
                        print("Epoch {}, test rmse: {:.4f}".format(epoch, test_rmse))
                        print()

            elif self.task == "ranking":
                for epoch in range(1, self.n_epochs + 1):
                    t0 = time.time()
                    neg = NegativeSampling(dataset, dataset.num_neg, self.batch_size)
                    n_batches = int(np.ceil(len(dataset.train_label_implicit) / self.batch_size))
                    for n in range(n_batches):
                        u, i, r = neg.next_batch()
                        self.sess.run([self.training_op],
                                      feed_dict={self.user_indices: u,
                                                 self.item_indices: i,
                                                 self.labels: r})

                    test_loss, test_acc, test_precision = \
                        self.sess.run([self.loss, self.accuracy, self.precision],
                                      feed_dict={self.user_indices: dataset.test_user_implicit,
                                                 self.item_indices: dataset.test_item_implicit,
                                                 self.labels: dataset.test_label_implicit})

                    if verbose > 0:
                        print("Epoch {}: training time: {:.4f}".format(epoch, time.time() - t0))

                        print("\ttest loss: {:.4f}".format(test_loss))
                        print("\ttest accuracy: {:.4f}".format(test_acc))
                        print("\ttest precision: {:.4f}".format(test_precision))

                        t4 = time.time()
                        mean_average_precision_10 = MAP_at_k(self, self.dataset, 10)
                        print("\t MAP @ {}: {:.4f}".format(10, mean_average_precision_10))
                        print("\t MAP @ 10 time: {:.4f}".format(time.time() - t4))

                        t5 = time.time()
                        mean_average_precision_100 = MAP_at_k(self, self.dataset, 100)
                        print("\t MAP @ {}: {:.4f}".format(100, mean_average_precision_100))
                        print("\t MAP @ 100 time: {:.4f}".format(time.time() - t5))

                        t6 = time.time()
                        mean_average_recall_10 = MAR_at_k(self, self.dataset, 10)
                        print("\t MAR @ {}: {:.4f}".format(10, mean_average_recall_10))
                        print("\t MAR @ 10 time: {:.4f}".format(time.time() - t6))

                        t7 = time.time()
                        mean_average_recall_100 = MAR_at_k(self, self.dataset, 100)
                        print("\t MAR @ {}: {:.4f}".format(100, mean_average_recall_100))
                        print("\t MAR @ 100 time: {:.4f}".format(time.time() - t7))

                        t8 = time.time()
                        HitRatio = HitRatio_at_k(self, self.dataset, 10)
                        print("\t HitRatio @ {}: {:.4f}".format(10, HitRatio))
                        print("\t HitRatio time: {:.4f}".format(time.time() - t8))

                        t9 = time.time()
                        NDCG = NDCG_at_k(self, self.dataset, 10)
                        print("\t NDCG @ {}: {:.4f}".format(10, NDCG))
                        print("\t NDCG time: {:.4f}".format(time.time() - t9))

    def predict(self, u, i):
        if self.task == "rating":
            try:
                pred = self.sess.run(self.pred, feed_dict={self.user_indices: [u],
                                                           self.item_indices: [i]})
                pred = np.clip(pred, 1, 5)
            except tf.errors.InvalidArgumentError:
                pred = self.global_mean
            return pred[0]

        elif self.task == "ranking":
            try:
                prob, pred = self.sess.run([self.y_prob, self.pred],
                                            feed_dict={self.user_indices: [u],
                                                       self.item_indices: [i]})
            except tf.errors.InvalidArgumentError:
                prob = 0.5
                pred = self.global_mean
            return prob[0], pred[0]

    def recommend_user(self, u, n_rec):
        user_indices = np.full(self.n_items, u)
        item_indices = np.arange(self.n_items)
        target = self.pred if self.task == "rating" else self.y_prob
        preds = self.sess.run(target, feed_dict={self.user_indices: user_indices,
                                                 self.item_indices: item_indices})
        preds = preds.ravel()
        consumed = self.dataset.train_user[u]
        count = n_rec + len(consumed)
        ids = np.argpartition(preds, -count)[-count:]
        rank = sorted(zip(ids, preds[ids]), key=lambda x: -x[1])
        return list(itertools.islice((rec for rec in rank if rec[0] not in consumed), n_rec))







#!/usr/bin/env python

# Copyright 2021-2022 Open ForBC for the benefit of INFN.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Authors:
# - Alessio Borriero <aleborri97@gmail.com>, 2021-2022
# - Daniele Monteleone <daniele.monteleone@to.infn.it>, 2022
# - Gabriele Gaetano Fronze' <gabriele.fronze@to.infn.it>, 2022

import time
import sys
import argparse

import tensorflow as tf
import tensorflow_datasets as tfds
import tensorflow.keras as keras
import numpy as np

# Global variables definition
batch_size = 1
n_epochs = 6
n_epochs_training = 50
n_of_class = 10
N = 150
teacher_size = 8


class TimeHistory(keras.callbacks.Callback):
    """A set of custom Keras callbacks to monitor Nvidia GPUs compute time."""

    def on_train_begin(self, logs={}):
        self.batch_times = []
        self.epoch_times = []
        self.training_time = []
        self.training_time_start = time.time()

    def on_predict_begin(self, logs={}):
        self.batch_times = []
        self.epoch_times = []
        self.training_time = []
        self.training_time_start = time.time()

    def on_train_batch_begin(self, batch, logs={}):
        self.batch_time_start = time.time()

    def on_train_batch_end(self, batch, logs={}):
        self.batch_times.append(time.time() - self.batch_time_start)

    def on_train_epoch_begin(self, batch, logs={}):
        self.epoch_time_start = time.time()

    def on_train_epoch_end(self, batch, logs={}):
        self.epoch_times.append(time.time() - self.epoch_time_start)

    def on_train_end(self, batch, logs={}):
        self.training_time.append(time.time() - self.training_time_start)

    def on_predict_batch_begin(self, batch, logs={}):
        self.batch_time_start = time.time()

    def on_predict_batch_end(self, batch, logs={}):
        self.batch_times.append(time.time() - self.batch_time_start)

    def on_predict_epoch_begin(self, batch, logs={}):
        self.epoch_time_start = time.time()

    def on_predict_epoch_end(self, batch, logs={}):
        self.epoch_times.append(time.time() - self.epoch_time_start)

    def on_predict_end(self, batch, logs={}):
        self.training_time.append(time.time() - self.training_time_start)


def load_MNIST_data():
    """Load and reshape the standard MNIST dataset."""
    (ds_train, ds_test), ds_info = tfds.load(
        "mnist",
        split=["train", "test"],
        shuffle_files=True,
        as_supervised=True,
        with_info=True,
    )

    def normalize_img(image, label):
        """Normalize images: `uint8` -> `float32`."""
        return tf.cast(image, tf.float32) / 255.0, label

    ds_train = ds_train.map(normalize_img, num_parallel_calls=tf.data.AUTOTUNE)
    ds_train = ds_train.cache()
    ds_train = ds_train.shuffle(ds_info.splits["train"].num_examples)
    ds_train = ds_train.batch(128)
    ds_train = ds_train.prefetch(tf.data.AUTOTUNE)

    ds_test = ds_test.map(normalize_img, num_parallel_calls=tf.data.AUTOTUNE)
    ds_test = ds_test.batch(128)
    ds_test = ds_test.cache()
    ds_test = ds_test.prefetch(tf.data.AUTOTUNE)

    return ds_train, ds_test


def create_MNIST_model():
    model = keras.models.Sequential(
        [
            keras.layers.Flatten(input_shape=(28, 28)),
            keras.layers.Dense(128, activation="relu"),
            keras.layers.Dense(64, activation="relu"),
            keras.layers.Dense(32, activation="relu"),
            keras.layers.Dense(10, activation="softmax"),
        ]
    )
    model.compile(
        optimizer=keras.optimizers.Adam(0.001),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=[keras.metrics.SparseCategoricalAccuracy()],
    )

    return model


def gen_stats_file_name(prefix):
    """Generate stats file name with prefix."""
    from time import strftime

    return f'stats_file_{prefix}_{strftime("%Y-%m-%d_%H-%M-%S")}.txt'


def training_benchmark(batch_size):
    """
    Perform training benchmark.

    Evaluates number of training inputs processed per second.
    """
    ds_train, _ = load_MNIST_data()
    model = create_MNIST_model()

    time_callback = TimeHistory()
    model.fit(
        ds_train,
        epochs=n_epochs_training,
        callbacks=[time_callback],
        batch_size=batch_size,
        verbose=1,
    )

    with open(gen_stats_file_name("training"), "w") as stats_file:
        for batch_time in time_callback.batch_times:
            stats_file.write(f"{batch_time}\n")

    print("TRAINING COMPLETED!")

    total_time = sum(time_callback.batch_times)

    print(
        f"total_time: {total_time}\n"
        f"avg_time_per_sample: {total_time / n_epochs_training / len(ds_train)}"
    )


def inference_benchmark(iteration_limit=None):
    """
    Perform inference benchmark.

    Evaluates number of Out-of-Sample inputs processed per second.
    """
    ds_train, ds_test = load_MNIST_data()
    model = create_MNIST_model()

    # Train the model without measuring its performance to prepare for inference
    model.fit(ds_train, epochs=n_epochs, verbose=0)
    print("TRAINING COMPLETED!")

    # Perform inference on Out-of-Sample multiple times to obtain average performance
    n_iterations = 0
    keep_running = True
    total_time = 0.0
    with open(gen_stats_file_name("inference"), "w") as stats_file:
        while keep_running:
            print(f"Iteration {n_iterations}")
            for batch in ds_test:  # online prediction (one sample at time)
                try:
                    for DS in batch[0]:
                        DS = np.expand_dims(DS, 0)
                        start_time = time.time()
                        _ = model(DS)
                        sample_time = time.time() - start_time
                        total_time += sample_time
                        stats_file.write(f"{sample_time}\n")
                        stats_file.flush()
                except KeyboardInterrupt:
                    keep_running = False
                    break
            n_iterations += 1
            if iteration_limit and n_iterations + 1 > iteration_limit:
                break

    print("INFERENCE COMPLETED!")
    print(
        f"total_time: {total_time}\n"
        f"avg_time_per_sample: {total_time / (len(ds_test) * n_iterations)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A ML MNIST benchmark")
    parser.add_argument("device_type", choices=["gpu", "cpu"], default="gpu")
    parser.add_argument(
        "mode", choices=["training", "inference", "test"], default="inference"
    )
    parser.add_argument("-g", "--gpu_index", default=0, nargs="?")
    parser.add_argument("-n", "--n_epochs_training", default=50, nargs="?", type=int)
    parser.add_argument("-t", "--test_mode", action="store_true")
    parser.add_argument(
        "-l",
        "--iteration_limit",
        help="Maximum number of inference iterations",
        type=int,
    )

    args = parser.parse_args()
    dev = args.device_type
    mode = args.mode
    gpu_index = args.gpu_index
    n_epochs_training = args.n_epochs_training

    # SET DEVICE
    if dev == "cpu":
        de = "/cpu:0"
    elif dev == "gpu":
        # Check GPU availability
        if tf.config.list_physical_devices("GPU") == 0:
            print("GPU unavailable. Aborting.")
            sys.exit(0)

        gpus = tf.config.list_physical_devices("GPU")

        if gpus:
            if len(gpus) >= gpu_index + 1:
                # Use dynamic GPU memory allocation
                tf.config.experimental.set_memory_growth(gpus[gpu_index], True)
            else:
                print(f"GPU {gpu_index} not found. Aborting.")
                sys.exit(0)
        else:
            print("No GPU found. Aborting.")
            sys.exit(0)

        de = f"/device:GPU:{gpu_index}"

    with tf.device(de):
        if mode == "training":
            training_benchmark(batch_size)
        elif mode == "inference":
            inference_benchmark(iteration_limit=args.iteration_limit)
        elif mode == "test":
            print("total_time: 0.0\navg_time_per_sample: 0.0")

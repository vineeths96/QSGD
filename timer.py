import time
import json
from contextlib import contextmanager
from io import StringIO

import numpy as np
import torch


class Timer:
    """
    Timer for PyTorch code
    Comes in the form of a contextmanager:
    Example:
    >>> timer = Timer()
    ... for i in range(10):
    ...     with timer("expensive operation"):
    ...         x = torch.randn(100)
    ... print(timer.summary())
    """

    def __init__(self, verbosity_level=1, skip_first=True, on_cuda=True):
        self.verbosity_level = verbosity_level
        self.log_fn = self.log_info
        self.skip_first = skip_first
        self.cuda_available = torch.cuda.is_available() and on_cuda

        self.reduce_times = []

        self.reset()

    def reset(self):
        """Reset the timer"""
        self.totals = {}  # Total time per label
        self.first_time = {}  # First occurrence of a label (start time)
        self.last_time = {}  # Last occurence of a label (end time)
        self.call_counts = {}  # Number of times a label occurred

    @contextmanager
    def __call__(self, label, epoch=-1.0, verbosity=1):
        # Don't measure this if the verbosity level is too high
        if verbosity > self.verbosity_level:
            yield
            return

        # Measure the time
        self._cuda_sync()
        start = time.time()
        yield
        self._cuda_sync()
        end = time.time()

        if label == 'batch.reduce':
            self.reduce_times.append(end-start)

        # Update first and last occurrence of this label
        if label not in self.first_time:
            self.first_time[label] = start
        self.last_time[label] = end

        # Update the totals and call counts
        if label not in self.totals and self.skip_first:
            self.totals[label] = 0.0
            del self.first_time[label]
            self.call_counts[label] = 0
        elif label not in self.totals and not self.skip_first:
            self.totals[label] = end - start
            self.call_counts[label] = 1
        else:
            self.totals[label] += end - start
            self.call_counts[label] += 1

        if self.call_counts[label] > 0:
            # We will reduce the probability of logging a timing
            # linearly with the number of time we have seen it.
            # It will always be recorded in the totals, though.
            if np.random.rand() < 1 / self.call_counts[label]:
                self.log_fn("timer", {"epoch": epoch, "value": end - start}, {"event": label})

    def summary(self):
        """
        Return a summary in string-form of all the timings recorded so far
        """
        if len(self.totals) > 0:
            with StringIO() as buffer:
                # total_avg_time = 0
                total_time = 0
                print(
                    "--- Timer summary -----------------------------------------------",
                    file=buffer,
                )
                print(
                    "  Event                          |  Count | Average time |  Frac.",
                    file=buffer,
                )
                for event_label in sorted(self.totals):
                    total = self.totals[event_label]
                    count = self.call_counts[event_label]
                    if count == 0:
                        continue
                    avg_duration = total / count
                    total_runtime = self.last_time[event_label] - self.first_time[event_label]
                    runtime_percentage = 100 * total / total_runtime
                    # total_avg_time += avg_duration if "." not in event_label else 0
                    total_time += total if event_label == "batch" else 0
                    print(
                        f"- {event_label:30s} | {count:6d} | {avg_duration:11.5f}s | {runtime_percentage:5.1f}%",
                        file=buffer,
                    )
                print(
                    "-----------------------------------------------------------------",
                    file=buffer,
                )
                event_label = "total_time"
                print(
                    f"- {event_label:30s} | {count:6d} | {total_time:11.5f}s |",
                    file=buffer,
                )
                print(
                    "-----------------------------------------------------------------",
                    file=buffer,
                )
                return buffer.getvalue()

    def save_summary(self, json_file_path):
        data = {}
        for event_label in sorted(self.totals):
            total = self.totals[event_label]
            count = self.call_counts[event_label]
            if count == 0:
                continue
            avg_duration = total / count
            data[event_label] = {
                "label": event_label,
                "average_duration": avg_duration,
                "n_events": count,
                "total_time": total,
            }

        data["reduce_times"] = self.reduce_times

        with open(json_file_path, "w") as fp:
            json.dump(data, fp)

    def _cuda_sync(self):
        """Finish all asynchronous GPU computations to get correct timings"""
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    def log_info(self, name, values, tags={}):
        value_list = []
        for key in sorted(values.keys()):
            value = values[key]
            value_list.append(f"{key}:{value:7.3f}")
        values = ", ".join(value_list)

        tag_list = []
        for key, tag in tags.items():
            tag_list.append(f"{key}:{tag}")
        tags = ", ".join(tag_list)

        print("{name:20s} - {values} ({tags})".format(name=name, values=values, tags=tags))

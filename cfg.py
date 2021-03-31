"""
"""
import os
from copy import deepcopy
from itertools import repeat

import numpy as np
from easydict import EasyDict as ED


__all__ = [
    "BaseCfg",
    "TrainCfg",
    "ModelCfg",
    "PlotCfg",
]


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


BaseCfg = ED()
# BaseCfg.db_dir = "/media/cfs/wenhao71/data/CPSC2021/"
BaseCfg.db_dir = "/home/taozi/Data/CinC2021/All_training_WFDB/"
BaseCfg.log_dir = os.path.join(_BASE_DIR, "log")
BaseCfg.model_dir = os.path.join(_BASE_DIR, "saved_models")
os.makedirs(BaseCfg.log_dir, exist_ok=True)
os.makedirs(BaseCfg.model_dir, exist_ok=True)
BaseCfg.fs = 200
BaseCfg.torch_dtype = "float"  # "double"


TrainCfg = ED()


ModelCfg = ED()


# configurations for visualization
PlotCfg = ED()
# default const for the plot function in dataset.py
# used only when corr. values are absent
# all values are time bias w.r.t. corr. peaks, with units in ms
PlotCfg.p_onset = -40
PlotCfg.p_offset = 40
PlotCfg.q_onset = -20
PlotCfg.s_offset = 40
PlotCfg.qrs_radius = 60
PlotCfg.t_onset = -100
PlotCfg.t_offset = 60
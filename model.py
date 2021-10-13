"""

Possible Solutions
------------------
1. segmentation (AF, non-AF) -> postprocess (merge too-close intervals, etc) -> onsets & offsets
2. sequence labelling (AF, non-AF) -> postprocess (merge too-close intervals, etc) -> onsets & offsets
3. per-beat (R peak detection first) classification (CNN, etc. + RR LSTM) -> postprocess (merge too-close intervals, etc) -> onsets & offsets
4. object detection (? onsets and offsets)
"""
from copy import deepcopy
from numbers import Real
from typing import Union, Optional, Sequence, Tuple, List, NoReturn, Any

import numpy as np
import pandas as pd
import torch
from torch import Tensor
from easydict import EasyDict as ED

# models from torch_ecg
from torch_ecg.torch_ecg.models.ecg_crnn import ECG_CRNN
from torch_ecg.torch_ecg.models.ecg_seq_lab_net import ECG_SEQ_LAB_NET
from torch_ecg.torch_ecg.models.unets import ECG_UNET, ECG_SUBTRACT_UNET
from torch_ecg.torch_ecg.models.rr_lstm import RR_LSTM
from cfg import ModelCfg
from signal_processing.ecg_preproc import merge_rpeaks
from utils.misc import mask_to_intervals


__all__ = [
    "ECG_SEQ_LAB_NET_CPSC2021",
    "ECG_UNET_CPSC2021",
    "ECG_SUBTRACT_UNET_CPSC2021",
    "RR_LSTM_CPSC2021",
]


class ECG_SEQ_LAB_NET_CPSC2021(ECG_SEQ_LAB_NET):
    """
    """
    __DEBUG__ = True
    __name__ = "ECG_SEQ_LAB_NET_CPSC2021"

    def __init__(self, config:ED, **kwargs:Any) -> NoReturn:
        """ finished, checked,

        Parameters
        ----------
        config: dict,
            other hyper-parameters, including kernel sizes, etc.
            ref. the corresponding config file

        Usage
        -----
        from cfg import ModelCfg
        task = "qrs_detection"  # or "main"
        model_cfg = deepcopy(ModelCfg[task])
        model_cfg.model_name = "seq_lab"
        model = ECG_SEQ_LAB_NET_CPSC2021(model_cfg)
        """
        super().__init__(config.classes, config.n_leads, config[config.model_name], **kwargs)
        self.task = config.task

    @torch.no_grad()
    def inference(self,
                  input:Union[Sequence[float],np.ndarray,Tensor],
                  bin_pred_thr:float=0.5,
                  **kwargs:Any) -> Any:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        kwargs: task specific key word arguments
        """
        if self.task == "qrs_detection":
            return self._inference_qrs_detection(input, bin_pred_thr, **kwargs)
        elif self.task == "main":
            return self._inference_main_task(input, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def inference_CPSC2021(self,
                           input:Union[Sequence[float],np.ndarray,Tensor],
                           bin_pred_thr:float=0.5,
                           **kwargs:Any) -> Any:
        """
        alias for `self.inference`
        """
        return self.inference(input, class_names, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def _inference_qrs_detection(self,
                                 input:Union[Sequence[float],np.ndarray,Tensor],
                                 bin_pred_thr:float=0.5,
                                 duration_thr:int=4*16,
                                 dist_thr:Union[int,Sequence[int]]=200,) -> Tuple[np.ndarray, List[np.ndarray]]:
        """ finished, checked,
        auxiliary function to `forward`, for CPSC2021,

        NOTE: each segment of input be better filtered using `_remove_spikes_naive`,
        and normalized to a suitable mean and std

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        duration_thr: int, default 4*16,
            minimum duration for a "true" qrs complex, units in ms
        dist_thr: int or sequence of int, default 200,
            if is sequence of int,
            (0-th element). minimum distance for two consecutive qrs complexes, units in ms;
            (1st element).(optional) maximum distance for checking missing qrs complexes, units in ms,
            e.g. [200, 1200]
            if is int, then is the case of (0-th element).

        Returns
        -------
        pred: ndarray,
            the array of scalar predictions
        rpeaks: list of ndarray,
            list of rpeak indices for each batch element
        """
        self.eval()
        _device = next(self.parameters()).device
        _dtype = next(self.parameters()).dtype
        _input = torch.as_tensor(input, dtype=_dtype, device=_device)
        if _input.ndim == 2:
            _input = _input.unsqueeze(0)  # add a batch dimension
        batch_size, channels, seq_len = _input.shape
        pred = self.forward(_input)
        pred = self.sigmoid(pred)
        pred = pred.cpu().detach().numpy().squeeze(-1)

        # prob --> qrs mask --> qrs intervals --> rpeaks
        rpeaks = _qrs_detection_post_process(
            pred=pred,
            fs=self.config.fs,
            reduction=self.config.reduction,
            bin_pred_thr=bin_pred_thr,
            duration_thr=duration_thr,
            dist_thr=dist_thr
        )

        return pred, rpeaks

    @torch.no_grad()
    def _inference_main_task(self,
                             input:Union[Sequence[float],np.ndarray,Tensor],
                             bin_pred_thr:float=0.5) -> Any:
        """ NOT finished, NOT checked,
        """
        self.eval()
        _device = next(self.parameters()).device
        _dtype = next(self.parameters()).dtype
        _input = torch.as_tensor(input, dtype=_dtype, device=_device)
        if _input.ndim == 2:
            _input = _input.unsqueeze(0)  # add a batch dimension
        raise NotImplementedError

    @staticmethod
    def from_checkpoint(path:str, device:Optional[torch.device]=None) -> torch.nn.Module:
        """ finished, checked,

        Parameters
        ----------
        path: str,
            path of the checkpoint
        device: torch.device, optional,
            map location of the model parameters,
            defaults "cuda" if available, otherwise "cpu"

        Returns
        -------
        model: Module,
            the model loaded from a checkpoint
        """
        _device = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
        ckpt = torch.load(path, map_location=_device)
        aux_config = ckpt.get("train_config", None) or ckpt.get("config", None)
        assert aux_config is not None, "input checkpoint has no sufficient data to recover a model"
        model = ECG_SEQ_LAB_NET_CPSC2021(config=ckpt["model_config"])
        model.load_state_dict(ckpt["model_state_dict"])
        return model


class ECG_UNET_CPSC2021(ECG_UNET):
    """
    """
    __DEBUG__ = True
    __name__ = "ECG_UNET_CPSC2021"
    
    def __init__(self, config:ED, **kwargs:Any) -> NoReturn:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        config: dict,
            other hyper-parameters, including kernel sizes, etc.
            ref. the corresponding config file

        Usage
        -----
        from cfg import ModelCfg
        task = "qrs_detection"  # or "main"
        model_cfg = deepcopy(ModelCfg[task])
        model_cfg.model_name = "unet"
        model = ECG_SEQ_LAB_NET_CPSC2021(model_cfg)
        """
        super().__init__(config.classes, config.n_leads, config[config.model_name], **kwargs)
        self.task = config.task

    @torch.no_grad()
    def inference(self,
                  input:Union[Sequence[float],np.ndarray,Tensor],
                  bin_pred_thr:float=0.5,
                  **kwargs:Any) -> Any:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        kwargs: task specific key word arguments
        """
        if self.task == "qrs_detection":
            return self._inference_qrs_detection(input, bin_pred_thr, **kwargs)
        elif self.task == "main":
            return self._inference_main_task(input, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def inference_CPSC2021(self,
                           input:Union[Sequence[float],np.ndarray,Tensor],
                           bin_pred_thr:float=0.5,
                           **kwargs:Any) -> Any:
        """
        alias for `self.inference`
        """
        return self.inference(input, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def _inference_qrs_detection(self,
                                 input:Union[Sequence[float],np.ndarray,Tensor],
                                 bin_pred_thr:float=0.5,
                                 duration_thr:int=4*16,
                                 dist_thr:Union[int,Sequence[int]]=200,) -> Tuple[np.ndarray, List[np.ndarray]]:
        """ finished, checked,
        auxiliary function to `forward`, for CPSC2021,

        NOTE: each segment of input be better filtered using `_remove_spikes_naive`,
        and normalized to a suitable mean and std

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        duration_thr: int, default 4*16,
            minimum duration for a "true" qrs complex, units in ms
        dist_thr: int or sequence of int, default 200,
            if is sequence of int,
            (0-th element). minimum distance for two consecutive qrs complexes, units in ms;
            (1st element).(optional) maximum distance for checking missing qrs complexes, units in ms,
            e.g. [200, 1200]
            if is int, then is the case of (0-th element).

        Returns
        -------
        pred: ndarray,
            the array of scalar predictions
        rpeaks: list of ndarray,
            list of rpeak indices for each batch element
        """
        self.eval()
        _device = next(self.parameters()).device
        _dtype = next(self.parameters()).dtype
        _input = torch.as_tensor(input, dtype=_dtype, device=_device)
        if _input.ndim == 2:
            _input = _input.unsqueeze(0)  # add a batch dimension
        batch_size, channels, seq_len = _input.shape
        pred = self.forward(_input)
        pred = self.sigmoid(pred)
        pred = pred.cpu().detach().numpy().squeeze(-1)

        # prob --> qrs mask --> qrs intervals --> rpeaks
        rpeaks = _qrs_detection_post_process(
            pred=pred,
            fs=self.config.fs,
            reduction=1,
            bin_pred_thr=bin_pred_thr,
            duration_thr=duration_thr,
            dist_thr=dist_thr
        )

        return pred, rpeaks

    @torch.no_grad()
    def _inference_main_task(self,
                             input:Union[Sequence[float],np.ndarray,Tensor],
                             bin_pred_thr:float=0.5,) -> Any:
        """
        """
        raise NotImplementedError

    @staticmethod
    def from_checkpoint(path:str, device:Optional[torch.device]=None) -> torch.nn.Module:
        """ finished, NOT checked,

        Parameters
        ----------
        path: str,
            path of the checkpoint
        device: torch.device, optional,
            map location of the model parameters,
            defaults "cuda" if available, otherwise "cpu"

        Returns
        -------
        model: Module,
            the model loaded from a checkpoint
        """
        _device = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
        ckpt = torch.load(path, map_location=_device)
        aux_config = ckpt.get("train_config", None) or ckpt.get("config", None)
        assert aux_config is not None, "input checkpoint has no sufficient data to recover a model"
        model = ECG_UNET_CPSC2021(config=ckpt["model_config"])
        model.load_state_dict(ckpt["model_state_dict"])
        return model


class ECG_SUBTRACT_UNET_CPSC2021(ECG_SUBTRACT_UNET):
    """
    """
    __DEBUG__ = True
    __name__ = "ECG_SUBTRACT_UNET_CPSC2021"

    def __init__(self, config:ED, **kwargs:Any) -> NoReturn:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        config: dict,
            other hyper-parameters, including kernel sizes, etc.
            ref. the corresponding config file

        Usage
        -----
        from cfg import ModelCfg
        task = "qrs_detection"  # or "main"
        model_cfg = deepcopy(ModelCfg[task])
        model_cfg.model_name = "unet"
        model = ECG_SEQ_LAB_NET_CPSC2021(model_cfg)
        """
        super().__init__(config.classes, config.n_leads, config[config.model_name], **kwargs)
        self.task = config.task

    @torch.no_grad()
    def inference(self,
                  input:Union[Sequence[float],np.ndarray,Tensor],
                  bin_pred_thr:float=0.5,
                  **kwargs:Any) -> Any:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        kwargs: task specific key word arguments
        """
        if self.task == "qrs_detection":
            return self._inference_qrs_detection(input, bin_pred_thr, **kwargs)
        elif self.task == "main":
            return self._inference_main_task(input, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def inference_CPSC2021(self,
                           input:Union[Sequence[float],np.ndarray,Tensor],
                           bin_pred_thr:float=0.5,
                           **kwargs:Any,) -> Any:
        """
        alias for `self.inference`
        """
        return self.inference(input, bin_pred_thr, **kwargs)

    @torch.no_grad()
    def _inference_qrs_detection(self,
                                 input:Union[Sequence[float],np.ndarray,Tensor],
                                 bin_pred_thr:float=0.5,
                                 duration_thr:int=4*16,
                                 dist_thr:Union[int,Sequence[int]]=200,) -> Tuple[np.ndarray, List[np.ndarray]]:
        """ finished, checked,
        auxiliary function to `forward`, for CPSC2021,

        NOTE: each segment of input be better filtered using `_remove_spikes_naive`,
        and normalized to a suitable mean and std

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., channels, seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        duration_thr: int, default 4*16,
            minimum duration for a "true" qrs complex, units in ms
        dist_thr: int or sequence of int, default 200,
            if is sequence of int,
            (0-th element). minimum distance for two consecutive qrs complexes, units in ms;
            (1st element).(optional) maximum distance for checking missing qrs complexes, units in ms,
            e.g. [200, 1200]
            if is int, then is the case of (0-th element).

        Returns
        -------
        pred: ndarray,
            the array of scalar predictions
        rpeaks: list of ndarray,
            list of rpeak indices for each batch element
        """
        self.eval()
        _device = next(self.parameters()).device
        _dtype = next(self.parameters()).dtype
        _input = torch.as_tensor(input, dtype=_dtype, device=_device)
        if _input.ndim == 2:
            _input = _input.unsqueeze(0)  # add a batch dimension
        batch_size, channels, seq_len = _input.shape
        pred = self.forward(_input)
        pred = self.sigmoid(pred)
        pred = pred.cpu().detach().numpy().squeeze(-1)

        # prob --> qrs mask --> qrs intervals --> rpeaks
        rpeaks = _qrs_detection_post_process(
            pred=pred,
            fs=self.config.fs,
            reduction=1,
            bin_pred_thr=bin_pred_thr,
            duration_thr=duration_thr,
            dist_thr=dist_thr
        )

        return pred, rpeaks

    @torch.no_grad()
    def _inference_main_task(self,
                             input:Union[Sequence[float],np.ndarray,Tensor],
                             bin_pred_thr:float=0.5,) -> Any:
        """
        """
        raise NotImplementedError

    @staticmethod
    def from_checkpoint(path:str, device:Optional[torch.device]=None) -> torch.nn.Module:
        """ finished, NOT checked,

        Parameters
        ----------
        path: str,
            path of the checkpoint
        device: torch.device, optional,
            map location of the model parameters,
            defaults "cuda" if available, otherwise "cpu"

        Returns
        -------
        model: Module,
            the model loaded from a checkpoint
        """
        _device = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
        ckpt = torch.load(path, map_location=_device)
        aux_config = ckpt.get("train_config", None) or ckpt.get("config", None)
        assert aux_config is not None, "input checkpoint has no sufficient data to recover a model"
        model = ECG_SUBTRACT_UNET_CPSC2021(config=ckpt["model_config"])
        model.load_state_dict(ckpt["model_state_dict"])
        return model


class RR_LSTM_CPSC2021(RR_LSTM):
    """
    """
    __DEBUG__ = True
    __name__ = "RR_LSTM_CPSC2021"

    def __init__(self, config:ED, **kwargs:Any) -> NoReturn:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        config: dict,
            other hyper-parameters, including kernel sizes, etc.
            ref. the corresponding config file

        Usage
        -----
        from cfg import ModelCfg
        task = "rr_lstm"
        model_cfg = deepcopy(ModelCfg[task])
        model_cfg.model_name = "rr_lstm"
        model = ECG_SEQ_LAB_NET_CPSC2021(model_cfg)
        """
        super().__init__(config.classes, config.n_leads, config[config.model_name], **kwargs)

    @torch.no_grad()
    def inference(self,
                  input:Union[Sequence[float],np.ndarray,Tensor],
                  bin_pred_thr:float=0.5,) -> Any:
        """ NOT finished, NOT checked,

        Parameters
        ----------
        input: array_like,
            input tensor, of shape (..., seq_len)
        bin_pred_thr: float, default 0.5,
            the threshold for making binary predictions from scalar predictions
        """
        self.eval()
        _device = next(self.parameters()).device
        _dtype = next(self.parameters()).dtype
        _input = torch.as_tensor(input, dtype=_dtype, device=_device)
        if _input.ndim == 2:
            _input = _input.unsqueeze(0)  # add a batch dimension
        elif _input.ndim == 1:
            _input = _input.unsqueeze(0).unsqueeze(0)  # add a batch dimension and a channel dimension
        _input = _input.permute(2,0,1)  # (batch_size, n_channels, seq_len) -> (seq_len, batch_size, n_channels)
        raise NotImplementedError

    @torch.no_grad()
    def inference_CPSC2021(self,
                           input:Union[Sequence[float],np.ndarray,Tensor],
                           bin_pred_thr:float=0.5,) -> Any:
        """
        alias for `self.inference`
        """
        return self.inference(input, class_names, bin_pred_thr)

    @staticmethod
    def from_checkpoint(path:str, device:Optional[torch.device]=None) -> torch.nn.Module:
        """

        Parameters
        ----------
        path: str,
            path of the checkpoint
        device: torch.device, optional,
            map location of the model parameters,
            defaults "cuda" if available, otherwise "cpu"

        Returns
        -------
        model: Module,
            the model loaded from a checkpoint
        """
        _device = device or (torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu"))
        ckpt = torch.load(path, map_location=_device)
        aux_config = ckpt.get("train_config", None) or ckpt.get("config", None)
        assert aux_config is not None, "input checkpoint has no sufficient data to recover a model"
        model = RR_LSTM_CPSC2021(config=ckpt["model_config"])
        model.load_state_dict(ckpt["model_state_dict"])
        return model


def _qrs_detection_post_process(pred:np.ndarray,
                                fs:Real,
                                reduction:int,
                                bin_pred_thr:float=0.5,
                                skip_dist:int=500,
                                duration_thr:int=4*16,
                                dist_thr:Union[int,Sequence[int]]=200,) -> List[np.ndarray]:
    """ finished, checked,

    prob --> qrs mask --> qrs intervals --> rpeaks

    Parameters
    ----------
    pred: ndarray,
        array of predicted probability
    fs: real number,
        sampling frequency of the ECG
    reduction: int,
        reduction (granularity) of `pred` w.r.t. the ECG
    bin_pred_thr: float, default 0.5,
        the threshold for making binary predictions from scalar predictions
    skip_dist: int, default 500,
        detected rpeaks with distance (units in ms) shorter than `skip_dist`
        to two ends of the ECG will be discarded
    duration_thr: int, default 4*16,
        minimum duration for a "true" qrs complex, units in ms
    dist_thr: int or sequence of int, default 200,
        if is sequence of int,
        (0-th element). minimum distance for two consecutive qrs complexes, units in ms;
        (1st element).(optional) maximum distance for checking missing qrs complexes, units in ms,
        e.g. [200, 1200]
        if is int, then is the case of (0-th element).
    """
    batch_size, prob_arr_len = pred.shape
    # print(batch_size, prob_arr_len)
    model_spacing = 1000 / fs  # units in ms
    model_granularity = reduction
    input_len = model_granularity * prob_arr_len
    _skip_dist = skip_dist / model_spacing  # number of samples
    _duration_thr = duration_thr / model_spacing / model_granularity
    _dist_thr = [dist_thr] if isinstance(dist_thr, int) else dist_thr
    assert len(_dist_thr) <= 2

    # mask = (pred > bin_pred_thr).astype(int)
    rpeaks = []
    for b_idx in range(batch_size):
        b_prob = pred[b_idx,...]
        b_mask = (b_prob > bin_pred_thr).astype(int)
        b_qrs_intervals = mask_to_intervals(b_mask, 1)
        # print(b_qrs_intervals)
        b_rpeaks = np.array([itv[0]+itv[1] for itv in b_qrs_intervals if itv[1]-itv[0] >= _duration_thr])
        b_rpeaks = (model_granularity * b_rpeaks / 2).astype(int)
        # print(f"before post-process, b_qrs_intervals = {b_qrs_intervals}")
        # print(f"before post-process, b_rpeaks = {b_rpeaks}")

        check = True
        dist_thr_inds = _dist_thr[0] / model_spacing
        while check:
            check = False
            b_rpeaks_diff = np.diff(b_rpeaks)
            for r in range(len(b_rpeaks_diff)):
                if b_rpeaks_diff[r] < dist_thr_inds:  # 200 ms
                    prev_r_ind = int(b_rpeaks[r]/model_granularity)  # ind in _prob
                    next_r_ind = int(b_rpeaks[r+1]/model_granularity)  # ind in _prob
                    if b_prob[prev_r_ind] > b_prob[next_r_ind]:
                        del_ind = r+1
                    else:
                        del_ind = r
                    b_rpeaks = np.delete(b_rpeaks, del_ind)
                    check = True
                    break
        if len(_dist_thr) == 1:
            b_rpeaks = b_rpeaks[np.where((b_rpeaks>=_skip_dist) & (b_rpeaks<input_len-_skip_dist))[0]]
            rpeaks.append(b_rpeaks)
            continue
        check = True
        # TODO: parallel the following block
        # CAUTION !!! 
        # this part is extremely slow in some cases (long duration and low SNR)
        dist_thr_inds = _dist_thr[1] / model_spacing
        while check:
            check = False
            b_rpeaks_diff = np.diff(b_rpeaks)
            for r in range(len(b_rpeaks_diff)):
                if b_rpeaks_diff[r] >= dist_thr_inds:  # 1200 ms
                    prev_r_ind = int(b_rpeaks[r]/model_granularity)  # ind in _prob
                    next_r_ind = int(b_rpeaks[r+1]/model_granularity)  # ind in _prob
                    prev_qrs = [itv for itv in b_qrs_intervals if itv[0]<=prev_r_ind<=itv[1]][0]
                    next_qrs = [itv for itv in b_qrs_intervals if itv[0]<=next_r_ind<=itv[1]][0]
                    check_itv = [prev_qrs[1], next_qrs[0]]
                    l_new_itv = mask_to_intervals(b_mask[check_itv[0]: check_itv[1]], 1)
                    if len(l_new_itv) == 0:
                        continue
                    l_new_itv = [[itv[0]+check_itv[0], itv[1]+check_itv[0]] for itv in l_new_itv]
                    new_itv = max(l_new_itv, key=lambda itv: itv[1]-itv[0])
                    new_max_prob = (b_prob[new_itv[0]:new_itv[1]]).max()
                    for itv in l_new_itv:
                        itv_prob = (b_prob[itv[0]:itv[1]]).max()
                        if itv[1] - itv[0] == new_itv[1] - new_itv[0] and itv_prob > new_max_prob:
                            new_itv = itv
                            new_max_prob = itv_prob
                    b_rpeaks = np.insert(b_rpeaks, r+1, 4*(new_itv[0]+new_itv[1]))
                    check = True
                    break
        b_rpeaks = b_rpeaks[np.where((b_rpeaks>=_skip_dist) & (b_rpeaks<input_len-_skip_dist))[0]]
        rpeaks.append(b_rpeaks)
    return rpeaks

"""A3T-GCN — Attention Temporal Graph Convolutional Network (plans/05 §5, plans/06 §1).

Built on `torch_geometric.nn.GCNConv`. At each timestep a GCN performs **spatial** message passing over
the (static) oblast adjacency; a GRU models the **temporal** dynamics; a learned **temporal attention**
pools the W hidden states into one node embedding; a linear head emits one logit per horizon
(Direct multi-horizon). Output: `[B, N, horizon]` logits.

Batching: the graph is shared across the batch, so we build a block-diagonal `edge_index` (per-graph
node offsets) and run all B*N nodes through GCNConv at once.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv


class A3TGCN(nn.Module):
    def __init__(self, in_channels: int, hidden: int = 64, horizon: int = 6,
                 num_layers: int = 1, dropout: float = 0.2):
        super().__init__()
        self.in_channels = in_channels
        self.hidden = hidden
        self.horizon = horizon
        self.gcn_layers = nn.ModuleList()
        c = in_channels
        for _ in range(max(1, num_layers)):
            self.gcn_layers.append(GCNConv(c, hidden))
            c = hidden
        self.gru = nn.GRU(hidden, hidden, batch_first=True)
        self.attn = nn.Linear(hidden, 1)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, horizon)
        self._last_attention: torch.Tensor | None = None  # [B, N, T] cached for XAI

    @staticmethod
    def _batched_edge_index(edge_index: torch.Tensor, B: int, N: int) -> torch.Tensor:
        E = edge_index.size(1)
        offset = (torch.arange(B, device=edge_index.device) * N).repeat_interleave(E)
        return edge_index.repeat(1, B) + offset.unsqueeze(0)

    def forward(self, X: torch.Tensor, edge_index: torch.Tensor,
                edge_weight: torch.Tensor | None = None, return_attention: bool = False):
        # X: [B, N, F, T]
        if X.dim() != 4:
            raise ValueError(f"expected X=[B,N,F,T], got {tuple(X.shape)}")
        B, N, Fdim, T = X.shape
        if Fdim != self.in_channels:
            raise ValueError(f"feature dim {Fdim} != in_channels {self.in_channels}")

        big_ei = self._batched_edge_index(edge_index, B, N)
        big_ew = edge_weight.repeat(B) if edge_weight is not None else None

        h_seq = []
        for t in range(T):
            h = X[:, :, :, t].reshape(B * N, Fdim)
            for gcn in self.gcn_layers:
                h = F.relu(gcn(h, big_ei, big_ew))
            h_seq.append(h.view(B, N, self.hidden))

        H = torch.stack(h_seq, dim=2).reshape(B * N, T, self.hidden)  # [B*N, T, hidden]
        out, _ = self.gru(H)                                         # [B*N, T, hidden]
        attn = torch.softmax(self.attn(out), dim=1)                  # [B*N, T, 1]
        context = (attn * out).sum(dim=1)                            # [B*N, hidden]
        logits = self.head(self.dropout(context)).view(B, N, self.horizon)

        self._last_attention = attn.view(B, N, T).detach()
        if return_attention:
            return logits, self._last_attention
        return logits

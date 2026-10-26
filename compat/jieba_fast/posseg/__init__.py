"""jieba_fast.posseg compatibility shim, forwarding to jieba.posseg."""

from jieba.posseg import *  # noqa: F401,F403
from jieba.posseg import cut, dt, lcut, pair  # noqa: F401

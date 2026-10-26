"""jieba_fast compatibility shim, forwarding to pure-Python jieba.

jieba_fast has no Python 3.11 wheel for Windows and needs MSVC to build from
source. GPT-SoVITS only relies on its jieba-compatible API, so when the real
package is unavailable scripts/setup.ps1 copies this stub into site-packages.
"""

import jieba as _jieba
from jieba import *  # noqa: F401,F403
from jieba import (  # noqa: F401
    add_word,
    cut,
    cut_for_search,
    del_word,
    initialize,
    lcut,
    lcut_for_search,
    load_userdict,
    setLogLevel,
    set_dictionary,
    suggest_freq,
    tokenize,
)

__version__ = "0.42.1+stub"

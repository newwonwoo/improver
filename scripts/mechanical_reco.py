"""호환 shim — 본체는 engine/mechanical_reco.py 로 이전(프로덕션 권고 통합).

기존 `from mechanical_reco import ...` 사용처(measure_reco_mechanical.py 등) 보존.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from engine.mechanical_reco import *  # noqa: F401,F403
from engine.mechanical_reco import (  # 명시 재노출(테스트·측정 사용 심볼)
    extract_verbatim, make_mechanical, score_adoption,
    score_specificity_strong,
)

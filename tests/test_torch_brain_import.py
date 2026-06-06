"""torch_brain 은 torch 미설치 환경에서도 import 돼야 한다 (S4 가드).

class TorchBrain(nn.Module) 가 import 시점에 nn 을 요구해 크래시하던 것 방지.
collect_torch_data 는 numpy만 쓰므로 torch 없이 호출 가능해야 한다.
"""
import importlib


def test_torch_brain_imports_without_torch():
    mod = importlib.import_module("engine.slm.torch_brain")
    # 적재 함수는 torch 가드 없이 존재해야 함
    assert hasattr(mod, "collect_torch_data")
    # 학습 함수는 torch 필요(가드 유지)
    assert hasattr(mod, "train_torch")

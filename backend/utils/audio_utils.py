from pathlib import Path
from typing import Tuple


def get_audio_duration(audio_path: str | Path) -> float:
    try:
        import librosa
        duration, _ = librosa.duration(path=str(audio_path))
        return duration
    except Exception:
        return 0.0


def validate_audio_file(file_path: str | Path, max_size: int) -> Tuple[bool, str]:
    path = Path(file_path)
    
    if not path.exists():
        return False, "文件不存在"
    
    if path.suffix.lower() not in [".wav", ".mp3"]:
        return False, "不支持的音频格式，仅支持wav和mp3"
    
    file_size = path.stat().st_size
    if file_size > max_size:
        return False, f"文件大小超过限制（最大{max_size // 1024 // 1024}MB）"
    
    return True, "验证通过"


def convert_to_wav(audio_path: str | Path, output_path: str | Path) -> Path:
    try:
        import librosa
        import soundfile as sf
        
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        sf.write(str(output_path), y, sr)
        return output_path
    except Exception as e:
        raise RuntimeError(f"音频转换失败: {e}")

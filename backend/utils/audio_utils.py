import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def get_audio_duration(audio_path: str | Path) -> float:
    audio_path = Path(audio_path)
    
    try:
        import librosa
        duration = librosa.get_duration(path=str(audio_path))
        logger.info(f"librosa获取音频时长成功: {audio_path.name}, 时长: {duration:.2f}秒")
        return duration
    except Exception as e:
        logger.warning(f"librosa获取音频时长失败: {e}")
    
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(audio_path))
        duration = len(audio) / 1000.0
        logger.info(f"pydub获取音频时长成功: {audio_path.name}, 时长: {duration:.2f}秒")
        return duration
    except Exception as e:
        logger.warning(f"pydub获取音频时长失败: {e}")
    
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        logger.info(f"soundfile获取音频时长成功: {audio_path.name}, 时长: {info.duration:.2f}秒")
        return info.duration
    except Exception as e:
        logger.warning(f"soundfile获取音频时长失败: {e}")
    
    logger.error(f"所有方法获取音频时长失败: {audio_path}")
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

@echo off
REM 模型缓存路径配置脚本
REM 运行此脚本后再执行其他Python程序，模型将缓存到指定目录

REM ModelScope 模型缓存
set MODELSCOPE_CACHE=D:\models\modelscope_cache

REM PyTorch 模型缓存
set TORCH_HOME=D:\models\torch_cache

REM Hugging Face 模型缓存（如果使用）
set HF_HOME=D:\models\huggingface_cache

REM pip 缓存（可选）
set PIP_CACHE_DIR=D:\models\pip_cache

echo ========================================
echo  模型缓存路径已配置:
echo ========================================
echo  MODELSCOPE_CACHE = %MODELSCOPE_CACHE%
echo  TORCH_HOME       = %TORCH_HOME%
echo  HF_HOME          = %HF_HOME%
echo  PIP_CACHE_DIR    = %PIP_CACHE_DIR%
echo ========================================
echo.
echo 现在可以运行你的Python程序了
echo.

cmd /k

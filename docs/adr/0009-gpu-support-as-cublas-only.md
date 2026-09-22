# 0009. GPU support is two cuBLAS files, and the CPU until they arrive

- **Status:** Accepted
- **Date:** 2026-09-21

## Context

CTranslate2 needs NVIDIA's cuBLAS to run Whisper on the GPU. The usual advice
installs cuBLAS and cuDNN, 1.3 GB. Measured in a virtualenv without PyTorch
(which otherwise supplies cuDNN unnoticed), Whisper never loads cuDNN. A model
also loads "on cuda" without cuBLAS and only fails on the first real decode:
on a fresh install the first dictation failed.

## Decision

Download only `cublas64_12.dll` and `cublasLt64_12.dll`, lifted out of NVIDIA's
PyPI wheel with HTTP range requests and CRC-checked (`components.py`). Before
choosing CUDA, check that cuBLAS actually loads (`_cuda.cublas_available`); if
not, decode on the CPU and say so once. The GPU is used as soon as the files
arrive.

## Consequences

- 550 MB instead of 1.3 GB, and no failed first dictation.
- Pinned to cuBLAS 12; a CTranslate2 that needs another major version needs
  this updated.

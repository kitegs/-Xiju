FROM python:3.12-slim

RUN groupadd --gid 10001 analyst \
    && useradd --uid 10001 --gid 10001 --create-home analyst \
    && pip install --no-cache-dir \
       pandas==2.3.1 polars==1.32.0 duckdb==1.3.2 pyarrow==21.0.0 \
       numpy==2.3.2 scipy==1.16.1 statsmodels==0.14.5 scikit-learn==1.7.1 \
       openpyxl==3.1.5 matplotlib==3.10.5 seaborn==0.13.2

USER 10001:10001
WORKDIR /tmp

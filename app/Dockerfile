# Imagem do serviço "web" (API Flask servida pelo Gunicorn).
# A ordem das instruções vai do que muda menos para o que muda mais,
# para aproveitar o cache de camadas (ver docs/RELATORIO.md, parte A).
FROM python:3.12-slim

# Sem arquivos .pyc, logs sem buffer (aparecem na hora em `docker compose logs`)
# e sem o aviso de versão do pip.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Usuário sem privilégios (RNF04) e diretório de uploads pertencente a ele.
# O UID/GID fixo (10001) deixa a permissão previsível dentro do volume "fotos".
RUN groupadd --system --gid 10001 appuser \
 && useradd --system --uid 10001 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/uploads \
 && chown appuser:appuser /app/uploads

# Dependências primeiro: esta camada só é refeita se o requirements.txt mudar.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código por último: muda com frequência e invalida só as camadas abaixo dele.
COPY app.py .

# UID:GID numérico (o mesmo do appuser): plataformas como o Kubernetes só
# conseguem verificar "não é root" quando o usuário é numérico.
USER 10001:10001

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app:app"]

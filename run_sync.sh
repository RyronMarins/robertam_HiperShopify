#!/bin/bash
cd /home/gramma/sincronizacao_shopify/scripts
source /home/gramma/sincronizacao_shopify/venv/bin/activate
python3 test_sync.py >> ../logs/sync.log 2>&1
deactivate
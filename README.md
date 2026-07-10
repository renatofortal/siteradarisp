# RadarISP — sync automático InfoJobs

Workflow (GitHub Actions) que busca vagas públicas de telecom/fibra/internet na InfoJobs e envia para https://radarisp.com.br.

Roda automaticamente **2× por dia**: 10:00 e 15:00 (horário de Brasília).

## Segredo necessário

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

- Nome: `RADARISP_SYNC_KEY`
- Valor: a chave gerada no WordPress (mesmo valor da option `radarisp_gupy_sync_key`)

## Rodar manualmente

Actions → **Sync InfoJobs → RadarISP** → **Run workflow**

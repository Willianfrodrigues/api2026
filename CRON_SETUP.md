# Configuração do scheduler de sync

O Vercel Hobby só permite 1 cron por dia. O endpoint `/api/cron/run`
é compatível com qualquer scheduler externo gratuito.

## Opção 1 — cron-job.org (recomendado, gratuito)

1. Crie uma conta em https://cron-job.org
2. New cronjob → URL: `https://SEU_DOMINIO/api/cron/run`
3. Header: `Authorization: Bearer SEU_CRON_SECRET`
4. Crie um job para CADA horário que você configurou nos transfers:

| Expressão cron | Horário BRT | Uso                        |
|----------------|-------------|----------------------------|
| `0 3 * * *`    | 00:00       | Sync diário d-3 (backfill) |
| `0 11 * * *`   | 08:00       | Update intraday             |
| `0 14 * * *`   | 11:00       | Update intraday             |
| `0 18 * * *`   | 15:00       | Update intraday             |
| `0 22 * * *`   | 19:00       | Update intraday final       |

> BRT = UTC-3, então 00:00 BRT = 03:00 UTC

## Opção 2 — EasyCron (gratuito até 200 execuções/mês)

Mesmo processo que cron-job.org.
URL: https://www.easycron.com

## Opção 3 — Vercel cron único às 00:00 (já configurado)

O `vercel.json` já tem `"0 3 * * *"` (= 00:00 BRT).
Isso executa apenas o sync diário d-3 automaticamente.
Os syncs intraday precisam ser disparados manualmente pelo botão ▶
ou via scheduler externo conforme acima.

## URL do endpoint

```
GET https://SEU_DOMINIO/api/cron/run
Authorization: Bearer SEU_CRON_SECRET

# Para forçar um slot específico:
GET https://SEU_DOMINIO/api/cron/run?slot=08:00
Authorization: Bearer SEU_CRON_SECRET
```

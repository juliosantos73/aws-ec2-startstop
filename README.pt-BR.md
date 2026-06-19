# aws-ec2-startstop

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

Uma única função AWS Lambda que **inicia e para instâncias EC2** em todas as regiões automaticamente, usando regras do EventBridge (CloudWatch Events).

---

## Como funciona

Duas regras do EventBridge invocam a mesma função Lambda em horários configurados, passando um payload JSON que indica qual ação executar. O Lambda percorre todas as regiões AWS habilitadas e inicia ou para as instâncias que possuem a tag `ScheduledStartStop = True`.

```
EventBridge (EC2start, cron)  ──► Lambda (lambda_function) ──► Instâncias EC2 (todas as regiões)
EventBridge (EC2stop,  cron)  ──►         │
                                          └── Filtra pela tag: ScheduledStartStop = True
```

---

## Funcionalidades

- Um único Lambda gerencia as ações de iniciar e parar
- Varre **todas as regiões AWS habilitadas** automaticamente
- Filtragem server-side — somente instâncias com a tag correta são retornadas pela API
- Chamadas paginadas — funciona corretamente em qualquer escala
- Retry adaptativo — lida automaticamente com throttling da API da AWS
- Modo dry run — teste sem afetar nenhuma instância
- Logs JSON estruturados — compatíveis com queries do CloudWatch Insights
- Configurável via variáveis de ambiente — sem necessidade de alterar o código

---

## Pré-requisitos

- Uma conta AWS com permissões para criar funções Lambda, roles IAM e regras do EventBridge
- Python 3.12+ (somente para desenvolvimento local)
- AWS CLI configurado (opcional, para deploy via linha de comando)

---

## 1. Adicionar tag nas instâncias EC2

Adicione a seguinte tag em cada instância que deseja gerenciar:

| Chave                | Valor  |
|----------------------|--------|
| `ScheduledStartStop` | `True` |

> Instâncias **sem** essa tag são completamente ignoradas.

---

## 2. Criar o IAM execution role

O Lambda precisa de uma role com a seguinte policy. Você pode criá-la pelo Console da AWS (IAM → Roles → Criar role → Lambda) ou via AWS CLI:

**Policy document** — salve como `ec2-startstop-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

**AWS CLI:**

```bash
# Criar a role
aws iam create-role \
  --role-name ec2-startstop-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Associar a policy
aws iam put-role-policy \
  --role-name ec2-startstop-role \
  --policy-name ec2-startstop-policy \
  --policy-document file://ec2-startstop-policy.json
```

---

## 3. Fazer o deploy da função Lambda

### Opção A — Console da AWS

1. Acesse **Lambda → Criar função**
2. Nome: `ec2-startstop` | Runtime: **Python 3.12** | Arquitetura: `x86_64`
3. Execution role: selecione a role criada no passo 2
4. Faça upload do arquivo `lambda_function.py` (ou cole o código diretamente no editor inline)
5. Handler: `lambda_function.lambda_handler`
6. Timeout: **5 minutos** (o padrão de 3 s é insuficiente para varreduras multi-região)
7. Salvar

### Opção B — AWS CLI

```bash
# Empacotar a função
zip lambda_function.zip lambda_function.py

# Obter o ARN da role (substitua pelo ID da sua conta)
ROLE_ARN=$(aws iam get-role --role-name ec2-startstop-role --query Role.Arn --output text)

# Criar a função
aws lambda create-function \
  --function-name ec2-startstop \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --timeout 300

# Para atualizar após mudanças no código:
aws lambda update-function-code \
  --function-name ec2-startstop \
  --zip-file fileb://lambda_function.zip
```

---

## 4. Configurar as regras do EventBridge

Crie duas regras que invocam o mesmo Lambda com payloads diferentes.

### Console da AWS

1. Acesse **EventBridge → Rules → Criar regra**
2. Selecione **Schedule** e configure a expressão cron
3. Target: **Lambda function** → `ec2-startstop`
4. Em **Configure input**, selecione **Constant (JSON text)** e insira o payload abaixo

| Nome da regra | Exemplo de cron (UTC)      | JSON de entrada         | Descrição            |
|---------------|----------------------------|-------------------------|----------------------|
| `EC2start`    | `cron(0 11 ? * MON-FRI *)` | `{"action": "start"}`   | Inicia às 08:00 BRT  |
| `EC2stop`     | `cron(0 23 ? * MON-FRI *)` | `{"action": "stop"}`    | Para às 20:00 BRT    |

> Ajuste as expressões cron conforme seu fuso horário e horário desejado.

### AWS CLI

```bash
LAMBDA_ARN=$(aws lambda get-function --function-name ec2-startstop --query Configuration.FunctionArn --output text)

# Regra EC2start
aws events put-rule \
  --name EC2start \
  --schedule-expression "cron(0 11 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule EC2start \
  --targets "Id=1,Arn=$LAMBDA_ARN,Input={\"action\":\"start\"}"

# Regra EC2stop
aws events put-rule \
  --name EC2stop \
  --schedule-expression "cron(0 23 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule EC2stop \
  --targets "Id=1,Arn=$LAMBDA_ARN,Input={\"action\":\"stop\"}"

# Permitir que o EventBridge invoque o Lambda
aws lambda add-permission \
  --function-name ec2-startstop \
  --statement-id AllowEventBridgeStart \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name EC2start --query RuleArn --output text)

aws lambda add-permission \
  --function-name ec2-startstop \
  --statement-id AllowEventBridgeStop \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name EC2stop --query RuleArn --output text)
```

---

## Configuração

O comportamento da função pode ser ajustado via **variáveis de ambiente do Lambda** — sem necessidade de alterar o código.

| Variável    | Padrão               | Descrição                                                   |
|-------------|----------------------|-------------------------------------------------------------|
| `TAG_KEY`   | `ScheduledStartStop` | Chave da tag usada para identificar as instâncias gerenciadas |
| `TAG_VALUE` | `True`               | Valor esperado da tag (sensível a maiúsculas)               |
| `DRY_RUN`   | `false`              | Defina como `true` para registrar ações sem executá-las     |

Para configurar via CLI:

```bash
aws lambda update-function-configuration \
  --function-name ec2-startstop \
  --environment "Variables={TAG_KEY=ScheduledStartStop,TAG_VALUE=True,DRY_RUN=false}"
```

---

## Testes

### Dry run pelo console do Lambda

Acesse **Lambda → Testar** e use os seguintes payloads:

```json
{ "action": "start", "dry_run": true }
```

```json
{ "action": "stop", "dry_run": true }
```

Nenhuma instância será iniciada ou parada. O log exibirá quais instâncias _seriam_ afetadas.

### Dry run via AWS CLI

```bash
aws lambda invoke \
  --function-name ec2-startstop \
  --payload '{"action":"stop","dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Monitoramento

Todos os logs são JSON estruturado, facilitando queries no **CloudWatch Logs Insights**.

**Ver todas as instâncias afetadas hoje:**

```
fields @timestamp, action, region, instances
| filter ispresent(instances)
| sort @timestamp desc
| limit 50
```

**Ver erros:**

```
fields @timestamp, region, error
| filter ispresent(error)
| sort @timestamp desc
```

---

## Desenvolvimento local

```bash
# Instalar dependências
pip install -r requirements-dev.txt

# Dry run local (requer credenciais AWS configuradas)
python -c "
from lambda_function import lambda_handler
result = lambda_handler({'action': 'stop', 'dry_run': True}, None)
print(result)
"
```

---

## Contribuindo

Contribuições são bem-vindas! Por favor:

1. Faça um fork do repositório
2. Crie uma branch: `git checkout -b feature/sua-feature`
3. Faça commit das alterações: `git commit -m 'Adiciona sua feature'`
4. Faça push: `git push origin feature/sua-feature`
5. Abra um Pull Request

Mantenha os PRs focados — uma feature ou correção por PR.

---

## Licença

[MIT](LICENSE) — © Júlio César Santos

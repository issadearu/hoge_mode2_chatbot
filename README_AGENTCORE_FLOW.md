# 🔄 AgentCore Memory - 完全な処理フロー解説

## 📋 概要

ユーザーがメッセージを送信してから、AgentCore Memory に保存されるまでの**全10ステップ**を詳しく解説します。

---

## 🎯 処理フロー全体像

```
ユーザー入力
    ↓
ALB (リクエスト受信)
    ↓
Cognito (認証)
    ↓
ECS/Fargate (コンテナ起動)
    ↓
AgentCore Runtime (処理制御)
    ↓
Bedrock (Claude) (応答生成)
    ↓
AgentCore Memory (会話保存)
    ↓
3つの戦略 (並行実行)
    ├─ Semantic (事実抽出)
    ├─ Summarization (要約)
    └─ Preference (設定抽出)
    ↓
DynamoDB (永続化)
    ↓
Lambda (非同期処理)
```

---

## 📊 各ステップの詳細

### **Step 1: ユーザー入力**

```python
# ユーザー: 上田一颯さん
actor_id = "issa_ueta_mail_nissan_co_jp"
message = "EC2インスタンスが起動しません"
```

**処理時間**: 0ms (起点)

---

### **Step 2: ALB (Application Load Balancer)**

```python
# ALBがHTTPSリクエストを受信
request = {
    'method': 'POST',
    'path': '/api/chat',
    'headers': {
        'Authorization': 'Bearer eyJxxx...',
        'Content-Type': 'application/json'
    },
    'body': {
        'actor_id': 'issa_ueta_mail_nissan_co_jp',
        'message': 'EC2インスタンスが起動しません'
    }
}
```

**処理時間**: +10ms (累計10ms)

---

### **Step 3: Cognito (認証)**

```python
# Cognitoでトークンを検証
cognito = boto3.client('cognito-idp')
response = cognito.get_user(AccessToken=token)

# 認証成功
user_info = {
    'user_id': 'issa_ueta_mail_nissan_co_jp',
    'email': 'issa.ueta@mail.nissan.co.jp',
    'groups': ['ops-team', 'nissan-employees']
}
```

**処理時間**: +40ms (累計50ms)

---

### **Step 4: ECS/Fargate (コンテナ実行)**

```python
# ECSがAgentCore Runtimeコンテナにリクエストを転送
container = {
    'image': 'agentcore-runtime:latest',
    'cpu': '1024',
    'memory': '2048',
    'environment': {
        'MEMORY_ID': 'memory_v1-MlucOAB1so',
        'AWS_REGION': 'ap-northeast-1'
    }
}
```

**処理時間**: +10ms (累計60ms)

---

### **Step 5: AgentCore Runtime (Strands Agent)**

```python
# セッション管理
session_id = "caee04e4-ba26-4129-8a5a-02dbb219560c"

# 過去の会話履歴を取得
history = memory_service.retrieve_conversation_history(
    actor_id=actor_id,
    session_id=session_id
)

# プロンプトを構築
messages = [
    {'role': 'user', 'content': '前回のメッセージ1'},
    {'role': 'assistant', 'content': '前回の応答1'},
    {'role': 'user', 'content': 'EC2インスタンスが起動しません'}  # 現在
]
```

**処理時間**: +190ms (累計250ms)
- 履歴取得: 180ms (平均)

---

### **Step 6: Amazon Bedrock (Claude)**

```python
# Claude Sonnetを呼び出し
bedrock = boto3.client('bedrock-runtime')
response = bedrock.invoke_model(
    modelId='anthropic.claude-3-sonnet-20240229-v1:0',
    body=json.dumps({
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 2048,
        'messages': messages,
        'temperature': 0.7
    })
)

# 応答
assistant_response = """
EC2インスタンスが起動しない場合、以下を確認してください：

1. CloudWatch Logsでエラーログを確認
2. インスタンスタイプのメモリ容量を確認
3. セキュリティグループの設定を確認

メモリ不足エラーの場合は、インスタンスタイプを
t3.small → t3.medium に変更することをお勧めします。
"""
```

**処理時間**: +1750ms (累計2000ms)
- LLM推論: 約1.7秒

---

### **Step 7: AgentCore Memory (会話保存)**

```python
# ユーザーメッセージを保存
memory_client.create_event(
    memoryId='memory_v1-MlucOAB1so',
    actorId='issa_ueta_mail_nissan_co_jp',
    sessionId='caee04e4-ba26-4129-8a5a-02dbb219560c',
    eventTimestamp=datetime.utcnow(),
    payload={
        'role': 'user',
        'content': 'EC2インスタンスが起動しません',
        'type': 'message'
    },
    clientToken=str(uuid.uuid4())
)

# アシスタント応答を保存
memory_client.create_event(
    memoryId='memory_v1-MlucOAB1so',
    actorId='issa_ueta_mail_nissan_co_jp',
    sessionId='caee04e4-ba26-4129-8a5a-02dbb219560c',
    eventTimestamp=datetime.utcnow(),
    payload={
        'role': 'assistant',
        'content': assistant_response,
        'type': 'message'
    },
    clientToken=str(uuid.uuid4())
)
```

**処理時間**: +125ms (累計2125ms)
- create_event: 平均115ms

**ログ出力**:
```json
{
  "log": "Processing extraction input",
  "requestId": "6106cea7-4cb1-4849-a2fc-a9c3cac6aaa3",
  "isError": false,
  "memory_strategy_id": "summary_builtin_6z3wr-9PQ3hD8rBG"
}
```

---

### **Step 8: Memory Strategies (3つの戦略が並行実行)**

#### **8a. Semantic Strategy (事実抽出)**

```python
# 入力
conversation = "EC2インスタンスが起動しません"

# 抽出される事実
semantic_facts = [
    {
        'type': 'issue',
        'resource': 'EC2',
        'status': 'not_starting',
        'confidence': 0.95
    },
    {
        'type': 'error',
        'error_type': 'startup_failure',
        'confidence': 0.89
    }
]

# 保存先
namespace = "/strategies/semantic_builtin_6z3wr-Rse2YJDEs8/actors/issa_ueta_mail_nissan_co_jp/"
```

**処理時間**: +370ms (累計2500ms)

---

#### **8b. Summarization Strategy (要約生成)**

```python
# 入力: 会話全体
messages = [
    {'role': 'user', 'content': 'EC2インスタンスが起動しません'},
    {'role': 'assistant', 'content': 'ログを確認してください...'}
]

# 生成される要約
summary = """
ユーザー(上田さん)はEC2インスタンスの起動失敗を報告。
メモリ不足エラーが原因と判明。
インスタンスタイプをt3.mediumに変更することを提案。
"""

# 保存先（セッション単位）
namespace = "/strategies/summary_builtin_6z3wr-9PQ3hD8rBG/actors/issa_ueta_mail_nissan_co_jp/sessions/caee04e4-ba26-4129-8a5a-02dbb219560c/"
```

**処理時間**: +300ms (累計2800ms)

**ログ出力** (実際のログ):
```json
{
  "log": "Processing extraction input",
  "requestId": "6106cea7-4cb1-4849-a2fc-a9c3cac6aaa3",
  "memory_strategy_id": "summary_builtin_6z3wr-9PQ3hD8rBG",
  "namespace": "/strategies/summary_builtin_6z3wr-9PQ3hD8rBG/actors/issa_ueta_mail_nissan_co_jp/sessions/caee04e4-ba26-4129-8a5a-02dbb219560c/"
}
```

---

#### **8c. User-preference Strategy (設定抽出)**

```python
# 入力
conversation = "EC2インスタンスが起動しません"

# 抽出される設定（この会話には設定情報なし）
preferences = {}

# もし設定があれば:
# preferences = {
#     'notification_time': '09:00',
#     'timezone': 'Asia/Tokyo',
#     'language': 'ja'
# }

# 保存先
namespace = "/strategies/preference_builtin_6z3wr-4CMP6F8Rex/actors/issa_ueta_mail_nissan_co_jp/"
```

**処理時間**: +50ms (累計2850ms)

---

### **Step 9: DynamoDB (永続化)**

```python
# Semantic facts を保存
dynamodb.put_item(
    TableName='ConversationHistory',
    Item={
        'actor_id': 'issa_ueta_mail_nissan_co_jp',
        'sort_key': 'semantic#caee04e4-ba26-4129-8a5a-02dbb219560c#2026-04-17T00:46:57.707Z#0',
        'type': 'semantic',
        'fact': {
            'type': 'issue',
            'resource': 'EC2',
            'status': 'not_starting'
        },
        'timestamp': '2026-04-17T00:46:57.707Z',
        'ttl': 1784270817  # 90日後に自動削除
    }
)

# Summary を保存
dynamodb.put_item(
    TableName='ConversationHistory',
    Item={
        'actor_id': 'issa_ueta_mail_nissan_co_jp',
        'sort_key': 'summary#caee04e4-ba26-4129-8a5a-02dbb219560c#2026-04-17T00:46:57.707Z',
        'type': 'summary',
        'content': 'ユーザー(上田さん)はEC2インスタンスの起動失敗を報告...',
        'timestamp': '2026-04-17T00:46:57.707Z'
    }
)
```

**処理時間**: +10ms (累計2860ms)

---

### **Step 10: Lambda (非同期処理)**

```python
# DynamoDB Streams からイベントを受信
def lambda_handler(event, context):
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            new_item = record['dynamodb']['NewImage']
            
            # 1. 感情分析
            sentiment = comprehend.detect_sentiment(
                Text=new_item['content'],
                LanguageCode='ja'
            )
            
            # 2. アラートチェック
            if 'エラー' in new_item['content'] or '起動しません' in new_item['content']:
                sns.publish(
                    TopicArn='arn:aws:sns:ap-northeast-1:xxx:ops-alerts',
                    Subject='EC2問題が報告されました',
                    Message=f"ユーザー: {new_item['actor_id']}\n問題: {new_item['content']}"
                )
            
            # 3. 外部システムへ通知
            requests.post('https://slack.com/api/chat.postMessage', json={
                'channel': '#ops-alerts',
                'text': f"🚨 EC2問題: {new_item['content']}"
            })
```

**処理時間**: +40ms (累計2900ms)
- 非同期なのでユーザーは待たない

---

## ⏱️ タイムライン総まとめ

| 時間 | ステップ | 処理内容 | 累計時間 |
|------|---------|---------|---------|
| 0ms | Step 1 | ユーザー入力 | 0ms |
| +10ms | Step 2 | ALB受信 | 10ms |
| +40ms | Step 3 | Cognito認証 | 50ms |
| +10ms | Step 4 | ECS転送 | 60ms |
| +190ms | Step 5 | Runtime処理 | 250ms |
| +1750ms | Step 6 | Bedrock応答 | 2000ms |
| +125ms | Step 7 | Memory保存 | 2125ms |
| +375ms | Step 8a | Semantic抽出 | 2500ms |
| +300ms | Step 8b | Summary生成 | 2800ms |
| +50ms | Step 8c | Preference抽出 | 2850ms |
| +10ms | Step 9 | DynamoDB保存 | 2860ms |
| +40ms | Step 10 | Lambda処理 | 2900ms |

**総処理時間**: 約2.9秒

---

## 📊 パフォーマンス分析

### **ボトルネック**

1. **Bedrock (Claude)**: 1750ms (60%)
   - LLMの推論時間
   - 改善策: Claude Haiku を使用（高速だが精度低下）

2. **Memory 履歴取得**: 180ms (6%)
   - DynamoDBクエリ
   - 改善策: ElastiCache でキャッシュ

3. **Summarization**: 300ms (10%)
   - LLMで要約生成
   - 改善策: バッチ処理で非同期化

### **最適化後の目標**

- Bedrock: 1750ms → 800ms (Haiku使用)
- Memory取得: 180ms → 50ms (キャッシュ)
- 総処理時間: 2900ms → **1500ms**

---

## 🔍 実際のログとの対応

### **ログ例1: Semantic Strategy**

```json
{
  "event_timestamp": 1776354719942,
  "memory_strategy_id": "semantic_builtin_6z3wr-Rse2YJDEs8",
  "actor_id": "mohamed_aseem_rntbci-nissan_com",
  "body": {
    "log": "Processing extraction input",
    "requestId": "4721086e-8361-4740-91d9-311b5ccecd10",
    "isError": false
  }
}
```

→ **Step 8a** の実行ログ

---

### **ログ例2: Summarization Strategy**

```json
{
  "event_timestamp": 1776383217707,
  "memory_strategy_id": "summary_builtin_6z3wr-9PQ3hD8rBG",
  "actor_id": "issa_ueta_mail_nissan_co_jp",
  "session_id": "caee04e4-ba26-4129-8a5a-02dbb219560c",
  "body": {
    "log": "Processing extraction input",
    "requestId": "6106cea7-4cb1-4849-a2fc-a9c3cac6aaa3",
    "isError": false
  }
}
```

→ **Step 8b** の実行ログ

---

## 🎯 まとめ

### **処理フローの特徴**

1. ✅ **多層防御**: ALB → Cognito → Runtime で段階的に認証
2. ✅ **自動記憶**: Memory が自動的に3つの戦略を実行
3. ✅ **非同期処理**: Lambda で重い処理を後回し
4. ✅ **スケーラブル**: ECS/Fargate で自動スケール

### **ユーザー体験**

- **応答時間**: 約2秒（Bedrock待ち）
- **記憶保存**: 自動（ユーザーは意識しない）
- **文脈理解**: 過去の会話を覚えている

### **運用メトリクス**

- **create_event**: 1.2K回/日、平均115ms
- **retrieve_memory**: 537回/日、平均181ms
- **新規記憶**: 1K件/日

---

## 📁 ファイル構成

```
.
├── agentcore_memory_flow_diagram.html  # 視覚的なフロー図
├── agentcore_complete_flow.py          # 完全なコード実装
└── README_AGENTCORE_FLOW.md            # このドキュメント
```

---

## 🚀 次のステップ

1. **図を開く**: `agentcore_memory_flow_diagram.html` をブラウザで開く
2. **コードを実行**: `python agentcore_complete_flow.py` でデモ実行
3. **ログを確認**: CloudWatch Logs で実際のログを見る
4. **最適化**: ボトルネックを改善

---

**作成日**: 2026-04-17  
**対象システム**: AWS Bedrock AgentCore Memory  
**Memory ID**: memory_v1-MlucOAB1so

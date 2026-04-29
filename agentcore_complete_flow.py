"""
AgentCore Memory - ユーザーインプットから保存までの完全な処理フロー
実際のコード実装例
"""

import boto3
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import time
from botocore.exceptions import ClientError


# ============================================================================
# Step 1-3: ユーザー認証フロー
# ============================================================================

class UserAuthenticationFlow:
    """ALB + Cognito による認証"""
    
    def __init__(self):
        self.cognito = boto3.client('cognito-idp')
        self.alb = boto3.client('elbv2')
    
    def handle_user_request(self, request: Dict) -> Dict:
        """
        ユーザーリクエストを処理
        
        Args:
            request: {
                'headers': {
                    'Authorization': 'Bearer eyJxxx...',
                    'Content-Type': 'application/json'
                },
                'body': {
                    'message': 'EC2が起動しません',
                    'actor_id': 'issa_ueta_mail_nissan_co_jp'
                }
            }
        """
        print("=" * 80)
        print("STEP 1-3: ユーザー認証フロー")
        print("=" * 80)
        
        # Step 1: ALBがリクエストを受信
        print("\n[ALB] リクエスト受信")
        print(f"  Time: {datetime.utcnow().isoformat()}")
        print(f"  User: {request['body']['actor_id']}")
        
        # Step 2: Cognitoでトークン検証
        token = request['headers']['Authorization'].replace('Bearer ', '')
        auth_result = self._verify_token(token)
        
        if not auth_result['authenticated']:
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        print(f"[Cognito] 認証成功")
        print(f"  User ID: {auth_result['user_id']}")
        print(f"  Groups: {auth_result['groups']}")
        
        # Step 3: ECS/Fargateへ転送
        return {
            'statusCode': 200,
            'authenticated': True,
            'user_info': auth_result
        }
    
    def _verify_token(self, token: str) -> Dict:
        """Cognitoトークンを検証"""
        try:
            response = self.cognito.get_user(AccessToken=token)
            return {
                'authenticated': True,
                'user_id': response['Username'],
                'groups': ['ops-team'],
                'attributes': response['UserAttributes']
            }
        except Exception as e:
            return {'authenticated': False, 'error': str(e)}


# ============================================================================
# Step 4-5: AgentCore Runtime
# ============================================================================

class AgentCoreRuntime:
    """AgentCore Runtime - Strands Agent"""
    
    def __init__(self):
        self.bedrock = boto3.client('bedrock-runtime', region_name='ap-northeast-1')
        self.memory_service = AgentCoreMemoryService()
    
    def process_user_message(self, actor_id: str, message: str, 
                            session_id: Optional[str] = None) -> Dict:
        """
        ユーザーメッセージを処理
        
        Args:
            actor_id: ユーザーID (例: issa_ueta_mail_nissan_co_jp)
            message: ユーザーメッセージ (例: "EC2が起動しません")
            session_id: セッションID (なければ新規作成)
        """
        print("\n" + "=" * 80)
        print("STEP 4-5: AgentCore Runtime 処理")
        print("=" * 80)
        
        start_time = time.time()
        
        # セッションIDの取得または作成
        if not session_id:
            session_id = str(uuid.uuid4())
            print(f"\n[Runtime] 新規セッション作成")
        else:
            print(f"\n[Runtime] 既存セッション使用")
        
        print(f"  Session ID: {session_id}")
        print(f"  Actor ID: {actor_id}")
        print(f"  Message: {message}")
        
        # Step 5a: 過去の会話履歴を取得
        print(f"\n[Runtime] 過去の会話履歴を取得中...")
        conversation_history = self.memory_service.retrieve_conversation_history(
            actor_id=actor_id,
            session_id=session_id
        )
        print(f"  取得した履歴: {len(conversation_history)}件")
        
        # Step 5b: プロンプトを構築
        prompt = self._build_prompt(message, conversation_history)
        
        # Step 6: Bedrockで応答生成
        print(f"\n[Runtime] Bedrock (Claude) を呼び出し中...")
        bedrock_start = time.time()
        
        assistant_response = self._call_bedrock(prompt)
        
        bedrock_latency = (time.time() - bedrock_start) * 1000
        print(f"  Bedrock応答時間: {bedrock_latency:.0f}ms")
        print(f"  応答: {assistant_response[:100]}...")
        
        # Step 7: 会話をMemoryに保存
        print(f"\n[Runtime] 会話をMemoryに保存中...")
        self.memory_service.save_conversation(
            actor_id=actor_id,
            session_id=session_id,
            user_message=message,
            assistant_response=assistant_response
        )
        
        total_latency = (time.time() - start_time) * 1000
        print(f"\n[Runtime] 処理完了")
        print(f"  総処理時間: {total_latency:.0f}ms")
        
        return {
            'session_id': session_id,
            'response': assistant_response,
            'latency_ms': total_latency
        }
    
    def _build_prompt(self, message: str, history: List[Dict]) -> List[Dict]:
        """プロンプトを構築"""
        messages = []
        
        # 過去の会話を追加
        for msg in history[-10:]:  # 直近10件
            messages.append({
                'role': msg['role'],
                'content': msg['content']
            })
        
        # 現在のメッセージを追加
        messages.append({
            'role': 'user',
            'content': message
        })
        
        return messages
    
    def _call_bedrock(self, messages: List[Dict]) -> str:
        """Bedrock (Claude) を呼び出し"""
        response = self.bedrock.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 2048,
                'messages': messages,
                'temperature': 0.7
            })
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']


# ============================================================================
# Step 7-9: AgentCore Memory Service
# ============================================================================

class AgentCoreMemoryService:
    """AgentCore Memory - 会話の保存と取得"""
    
    def __init__(self):
        self.bedrock_agent = boto3.client('bedrock-agent-runtime', 
                                         region_name='ap-northeast-1')
        self.memory_id = 'memory_v1-MlucOAB1so'
        self.dynamodb = boto3.resource('dynamodb')
        self.conversation_table = self.dynamodb.Table('ConversationHistory')
    
    def save_conversation(self, actor_id: str, session_id: str,
                         user_message: str, assistant_response: str):
        """
        会話をMemoryに保存
        
        これにより3つの戦略が自動的に実行される:
        1. Semantic Strategy: 事実抽出
        2. Summarization Strategy: 要約生成
        3. User-preference Strategy: 設定抽出
        """
        print("\n" + "=" * 80)
        print("STEP 7: AgentCore Memory - 会話保存")
        print("=" * 80)
        
        # ユーザーメッセージを保存
        print(f"\n[Memory] ユーザーメッセージを保存")
        user_event_id = self._create_event(
            actor_id=actor_id,
            session_id=session_id,
            payload={
                'role': 'user',
                'content': user_message,
                'type': 'message'
            }
        )
        print(f"  Event ID: {user_event_id}")
        
        # アシスタント応答を保存
        print(f"\n[Memory] アシスタント応答を保存")
        assistant_event_id = self._create_event(
            actor_id=actor_id,
            session_id=session_id,
            payload={
                'role': 'assistant',
                'content': assistant_response,
                'type': 'message'
            }
        )
        print(f"  Event ID: {assistant_event_id}")
        
        # この時点で自動的に3つの戦略が実行される
        print(f"\n[Memory] 3つの戦略が自動実行されます:")
        print(f"  1. Semantic Strategy: 事実情報を抽出")
        print(f"  2. Summarization Strategy: 会話を要約")
        print(f"  3. User-preference Strategy: ユーザー設定を抽出")
        
        return {
            'user_event_id': user_event_id,
            'assistant_event_id': assistant_event_id
        }
    
    def _create_event(self, actor_id: str, session_id: str, payload: Dict) -> str:
        """Memoryにイベントを作成"""
        start_time = time.time()
        
        params = {
            "memoryId": self.memory_id,
            "actorId": actor_id,
            "sessionId": session_id,
            "eventTimestamp": datetime.utcnow(),
            "payload": payload,
            "clientToken": str(uuid.uuid4()),
        }
        
        try:
            response = self.bedrock_agent.create_event(**params)
            event_id = response["event"]["eventId"]
            
            latency = (time.time() - start_time) * 1000
            print(f"  保存完了: {latency:.0f}ms")
            
            return event_id
        except ClientError as e:
            print(f"  ❌ エラー: {str(e)}")
            raise
    
    def retrieve_conversation_history(self, actor_id: str, 
                                     session_id: str) -> List[Dict]:
        """会話履歴を取得"""
        start_time = time.time()
        
        try:
            # DynamoDBから直接取得（高速）
            response = self.conversation_table.query(
                KeyConditionExpression='actor_id = :aid AND begins_with(sort_key, :sid)',
                ExpressionAttributeValues={
                    ':aid': actor_id,
                    ':sid': f"session#{session_id}"
                },
                ScanIndexForward=False,  # 新しい順
                Limit=20
            )
            
            messages = response.get('Items', [])
            messages.reverse()  # 古い順に並び替え
            
            latency = (time.time() - start_time) * 1000
            print(f"  取得完了: {latency:.0f}ms")
            
            return messages
        except Exception as e:
            print(f"  ❌ エラー: {str(e)}")
            return []


# ============================================================================
# Step 8: Memory Strategies (自動実行)
# ============================================================================

class MemoryStrategies:
    """
    3つのMemory戦略
    これらはAgentCore Memoryによって自動的に実行される
    """
    
    @staticmethod
    def semantic_strategy(conversation: str) -> Dict:
        """
        Semantic Strategy: 事実情報を抽出
        
        例:
        入力: "EC2が起動しません。メモリ不足エラーが出ています"
        出力: {
            'facts': [
                {'type': 'issue', 'resource': 'EC2', 'status': 'not_starting'},
                {'type': 'error', 'error_type': 'memory_shortage'}
            ]
        }
        """
        print("\n" + "=" * 80)
        print("STEP 8a: Semantic Strategy 実行")
        print("=" * 80)
        
        print(f"\n[Semantic] 事実情報を抽出中...")
        print(f"  入力: {conversation[:100]}...")
        
        # 実際にはBedrockのLLMで抽出
        facts = [
            {
                'type': 'issue',
                'resource': 'EC2',
                'status': 'not_starting',
                'confidence': 0.95
            },
            {
                'type': 'error',
                'error_type': 'memory_shortage',
                'confidence': 0.89
            }
        ]
        
        print(f"  抽出された事実: {len(facts)}件")
        for fact in facts:
            print(f"    - {fact['type']}: {fact.get('resource', fact.get('error_type'))}")
        
        # Namespace に保存
        namespace = "/strategies/semantic_builtin_6z3wr-Rse2YJDEs8/actors/{actor_id}/"
        print(f"  保存先: {namespace}")
        
        return {'facts': facts, 'namespace': namespace}
    
    @staticmethod
    def summarization_strategy(messages: List[Dict]) -> Dict:
        """
        Summarization Strategy: 会話を要約
        
        例:
        入力: 10往復の会話
        出力: "ユーザーはEC2のメモリ不足問題を報告。
               インスタンスタイプをt3.mediumに変更して解決。"
        """
        print("\n" + "=" * 80)
        print("STEP 8b: Summarization Strategy 実行")
        print("=" * 80)
        
        print(f"\n[Summarization] 会話を要約中...")
        print(f"  メッセージ数: {len(messages)}件")
        
        # 実際にはBedrockのLLMで要約
        summary = """
        ユーザー(上田さん)はEC2インスタンスの起動失敗を報告。
        メモリ不足エラーが原因と判明。
        インスタンスタイプをt3.mediumに変更することを提案。
        """
        
        print(f"  要約: {summary.strip()}")
        
        # Namespace に保存（セッション単位）
        namespace = "/strategies/summary_builtin_6z3wr-9PQ3hD8rBG/actors/{actor_id}/sessions/{session_id}/"
        print(f"  保存先: {namespace}")
        
        return {'summary': summary.strip(), 'namespace': namespace}
    
    @staticmethod
    def preference_strategy(conversation: str) -> Dict:
        """
        User-preference Strategy: ユーザー設定を抽出
        
        例:
        入力: "毎朝9時に通知してください"
        出力: {
            'preferences': {
                'notification_time': '09:00',
                'timezone': 'Asia/Tokyo'
            }
        }
        """
        print("\n" + "=" * 80)
        print("STEP 8c: User-preference Strategy 実行")
        print("=" * 80)
        
        print(f"\n[Preference] ユーザー設定を抽出中...")
        print(f"  入力: {conversation[:100]}...")
        
        # この会話には設定情報がない場合
        preferences = {}
        
        if not preferences:
            print(f"  抽出された設定: なし")
        else:
            print(f"  抽出された設定: {len(preferences)}件")
        
        # Namespace に保存
        namespace = "/strategies/preference_builtin_6z3wr-4CMP6F8Rex/actors/{actor_id}/"
        print(f"  保存先: {namespace}")
        
        return {'preferences': preferences, 'namespace': namespace}


# ============================================================================
# Step 9-10: DynamoDB & Lambda
# ============================================================================

class DynamoDBStorage:
    """DynamoDB への永続化"""
    
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table('ConversationHistory')
    
    def store_extracted_memories(self, actor_id: str, session_id: str,
                                 semantic_facts: List[Dict],
                                 summary: str,
                                 preferences: Dict):
        """抽出された記憶をDynamoDBに保存"""
        print("\n" + "=" * 80)
        print("STEP 9: DynamoDB 永続化")
        print("=" * 80)
        
        timestamp = datetime.utcnow().isoformat()
        
        # Semantic facts を保存
        print(f"\n[DynamoDB] Semantic facts を保存")
        for i, fact in enumerate(semantic_facts):
            self.table.put_item(Item={
                'actor_id': actor_id,
                'sort_key': f"semantic#{session_id}#{timestamp}#{i}",
                'type': 'semantic',
                'fact': fact,
                'timestamp': timestamp
            })
        print(f"  保存完了: {len(semantic_facts)}件")
        
        # Summary を保存
        if summary:
            print(f"\n[DynamoDB] Summary を保存")
            self.table.put_item(Item={
                'actor_id': actor_id,
                'sort_key': f"summary#{session_id}#{timestamp}",
                'type': 'summary',
                'content': summary,
                'timestamp': timestamp
            })
            print(f"  保存完了")
        
        # Preferences を保存
        if preferences:
            print(f"\n[DynamoDB] Preferences を保存")
            self.table.put_item(Item={
                'actor_id': actor_id,
                'sort_key': f"preference#{timestamp}",
                'type': 'preference',
                'preferences': preferences,
                'timestamp': timestamp
            })
            print(f"  保存完了")


class LambdaAsyncProcessing:
    """Lambda による非同期処理"""
    
    @staticmethod
    def process_dynamodb_stream_event(event: Dict):
        """
        DynamoDB Streams からのイベントを処理
        
        トリガー: DynamoDBに新しいレコードが追加された時
        """
        print("\n" + "=" * 80)
        print("STEP 10: Lambda 非同期処理")
        print("=" * 80)
        
        for record in event['Records']:
            if record['eventName'] == 'INSERT':
                new_item = record['dynamodb']['NewImage']
                
                print(f"\n[Lambda] 新しいレコードを検出")
                print(f"  Type: {new_item.get('type', {}).get('S')}")
                print(f"  Actor: {new_item.get('actor_id', {}).get('S')}")
                
                # 1. 分析処理
                LambdaAsyncProcessing._analyze_sentiment(new_item)
                
                # 2. アラートチェック
                LambdaAsyncProcessing._check_alerts(new_item)
                
                # 3. 他システムへの通知
                LambdaAsyncProcessing._notify_external_systems(new_item)
    
    @staticmethod
    def _analyze_sentiment(item: Dict):
        """感情分析"""
        print(f"  [Lambda] 感情分析を実行")
        # Amazon Comprehend などで分析
    
    @staticmethod
    def _check_alerts(item: Dict):
        """アラート条件をチェック"""
        print(f"  [Lambda] アラート条件をチェック")
        # エラーキーワードがあればSNS通知
    
    @staticmethod
    def _notify_external_systems(item: Dict):
        """外部システムへ通知"""
        print(f"  [Lambda] 外部システムへ通知")
        # Slack, Teams, 社内システムなどへ通知


# ============================================================================
# メイン実行フロー
# ============================================================================

def main():
    """完全な処理フローのデモ"""
    
    print("\n")
    print("=" * 80)
    print("AgentCore Memory - 完全な処理フロー")
    print("=" * 80)
    print("\n")
    
    # ユーザーリクエストを準備
    user_request = {
        'headers': {
            'Authorization': 'Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...',
            'Content-Type': 'application/json'
        },
        'body': {
            'message': 'EC2インスタンスが起動しません。メモリ不足エラーが表示されています。',
            'actor_id': 'issa_ueta_mail_nissan_co_jp'
        }
    }
    
    # Step 1-3: 認証
    auth_flow = UserAuthenticationFlow()
    auth_result = auth_flow.handle_user_request(user_request)
    
    if auth_result['statusCode'] != 200:
        print("認証失敗")
        return
    
    # Step 4-6: Runtime処理 (1回目のメッセージ)
    print("\n--- 1回目のメッセージ ---")
    runtime = AgentCoreRuntime()
    first_result = runtime.process_user_message(
        actor_id=user_request['body']['actor_id'],
        message=user_request['body']['message'],
        session_id=None  # 新規セッションを開始
    )
    
    # 2回目のメッセージ（同じセッションIDを使用）
    print("\n\n--- 2回目のメッセージ（同じセッション） ---")
    second_result = runtime.process_user_message(
        actor_id=user_request['body']['actor_id'],
        message="ありがとうございます。試してみます。",
        session_id=first_result['session_id'] # 既存のセッションIDを渡す
    )
    
    print(f"\n\n{'=' * 80}")
    print("最終結果")
    print("=" * 80)
    print(f"\nセッションID: {second_result['session_id']}")
    print(f"最終応答: {second_result['response'][:200]}...")
    print(f"総処理時間 (2回目): {second_result['latency_ms']:.0f}ms")
    
    # Step 8: 戦略実行（デモ）
    conversation = user_request['body']['message']
    
    semantic_result = MemoryStrategies.semantic_strategy(conversation)
    summary_result = MemoryStrategies.summarization_strategy([
        {'role': 'user', 'content': conversation}
    ])
    preference_result = MemoryStrategies.preference_strategy(conversation)
    
    # Step 9: DynamoDB保存
    db = DynamoDBStorage()
    db.store_extracted_memories(
        actor_id=user_request['body']['actor_id'],
        session_id=first_result['session_id'],
        semantic_facts=semantic_result['facts'],
        summary=summary_result['summary'],
        preferences=preference_result['preferences']
    )
    
    # Step 10: Lambda処理（デモ）
    mock_stream_event = {
        'Records': [{
            'eventName': 'INSERT',
            'dynamodb': {
                'NewImage': {
                    'actor_id': {'S': user_request['body']['actor_id']},
                    'type': {'S': 'semantic'},
                    'timestamp': {'S': datetime.utcnow().isoformat()}
                }
            }
        }]
    }
    
    LambdaAsyncProcessing.process_dynamodb_stream_event(mock_stream_event)
    
    print(f"\n\n{'=' * 80}")
    print("処理完了！")
    print("=" * 80)


if __name__ == "__main__":
    main()

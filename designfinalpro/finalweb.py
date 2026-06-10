import os
import chromadb
import time
import google.generativeai as genai
import streamlit as st

# 溫馨提醒：把程式碼分享給別人時，記得把真實的 API Key 藏起來喔！
# 透過 Streamlit 的保密機制讀取 API KEY
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=GOOGLE_API_KEY)

# 1. 讀取 TRPG 設定檔
print("正在讀取新的 TRPG 設定檔...")
with open("trpg_setting.txt", "r", encoding="utf-8") as file:
    text_data = file.read()

# 2. 改為用「單換行(\n)」來自動切分段落
chunks = [chunk.strip() for chunk in text_data.split("\n") if len(chunk.strip()) > 10]
print(f"文本已安全切割成 {len(chunks)} 個段落。")

# 3. 初始化 ChromaDB 並存入資料
print("正在啟動 ChromaDB 並建立向量資料...")
chroma_client = chromadb.PersistentClient(path="./chroma_data") 

# 【新增防呆機制】：強制清除舊的同名資料庫，確保 AI 不會混淆舊設定！
try:
    chroma_client.delete_collection(name="trpg_world")
    print("已成功清除舊的向量記憶...")
except Exception:
    pass # 如果原本就沒有舊資料，就忽略

# 建立全新的乾淨資料庫
collection = chroma_client.create_collection(name="trpg_world")

# 將段落轉成向量並存入資料庫
for i, chunk in enumerate(chunks):
    # 略過太短的無意義段落
    if len(chunk) < 5:
        continue
        
    success = False
    while not success:
        try:
            response = genai.embed_content(
                model="models/gemini-embedding-001",
                content=chunk,
                task_type="retrieval_document" 
            )
            embedding = response['embedding']
            
            collection.add(
                documents=[chunk],
                embeddings=[embedding],
                ids=[f"chunk_{i}"]
            )
            
            # 印出進度條，讓你不用乾等
            print(f"成功存入第 {i+1} / {len(chunks)} 個段落")
            
            # 正常情況下稍微停頓 2 秒
            time.sleep(2) 
            success = True # 成功了，跳出 while 迴圈進入下一個段落
            
        except Exception as e:
            # 如果捕捉到 429 頻率限制錯誤
            if "429" in str(e):
                print(f"⚠️ 撞到免費 API 頻率限制！GM 大腦休息 15 秒後繼續...")
                time.sleep(15) # 休息久一點再重試
            else:
                # 如果是其他未知的錯誤，就直接報錯停止
                raise e

print("資料建置大功告成！GM 大腦已經裝載了你的全新精簡設定。")

# 4. 測試檢索功能
print("\n--- 進入測試模式 ---")
user_input = input("請輸入你想查詢的設定 (例如：算盤珠有什麼功用？): ")

# 查詢時也需要用 Gemini 將使用者的問題轉成向量 (查詢使用 retrieval_query)
query_response = genai.embed_content(
    model="models/gemini-embedding-001",
    content=user_input,
    task_type="retrieval_query"
)
query_embedding = query_response['embedding']

# 從資料庫撈出最相關的 2 個段落
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=2
)

print("\n[AI GM 從資料庫撈出的相關設定如下：]")
for doc in results['documents'][0]:
    print(f"- {doc}")
    print("---")
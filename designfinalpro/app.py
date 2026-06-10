import streamlit as st
import chromadb
import google.generativeai as genai
import time
import random
import re

# --- 1. 基礎設定 ---
st.set_page_config(page_title="城隍的小差使 | AI TRPG", page_icon="🏮", layout="wide")

# 記得填入你的 API KEY (加上 .strip() 防止格式錯誤)
# 透過 Streamlit 的保密機制讀取 API KEY
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=GOOGLE_API_KEY)

# GM 模型設定 (System Prompt 大瘦身與重構)
gm_model = genai.GenerativeModel(
    model_name='gemini-3.1-flash-lite', 
    generation_config={"temperature": 0.2},
    system_instruction="""
    你是一位專業的 TRPG 遊戲主持人(GM)。
    你的知識來源嚴格僅限於下方提供的【世界觀與劇本資料】。

    【核心守則】：
    1. 嚴格遵守劇情：未提及的場景、物品絕對禁止編造。
    2. 非戰鬥場景：絕對不進行骰子判定，也不使用任何能力屬性。玩家只要主動詢問或提出合理行動，你就直接提供對應的線索或推進劇情。
    3. 嚴禁跳躍章節：嚴格按照劇本幕次推進。

    【物品與背包更新規則】(絕對防塞道具版)：
    1. 【嚴禁自動拾取】：當物品出現在場景中時，【絕對禁止】直接發送 [ITEMS: +物品] 標籤！必須等待玩家明確輸入「我要撿起」、「收入背包」等動作後，才能在下一回合給予。
    2. 【標籤發送時機】：只有在確認玩家主動帶走物品的那一回合，你才【必須】在回覆內容的最後一行（### OPTIONS ### 之前），附上獨立指令標籤：[ITEMS: +物品名稱] 或 [ITEMS: -物品名稱]。
    3. 範例：玩家成功拿走算盤珠時，回覆末尾加上：[ITEMS: +算盤珠]

    【戰鬥與判定機制】(進入第四幕戰鬥時啟動)：
    1. 戰鬥「絕對不使用」角色屬性加值。只看玩家擲出的 D20 骰面數字。
    2. 玩家行動後，你「只能」描寫動作起手式，接著立刻輸出【要求判定】並停止生成。
    3. 收到系統傳入的擲骰結果後，嚴格依據以下標準裁定並接續劇情：
       - 1～5：失敗，局勢惡化或主角受到傷害。
       - 6～10：部分成功，行動有效但伴隨代價。
       - 11～17：成功，造成明顯效果。
       - 18～19：大成功，額外壓制陰氣或保護孩子。
       - 20：極大成功，觸發城隍神力的預兆。
    4. 【戰鬥資源】：算盤珠可讓玩家重擲或結果提升一級；平安符可抵銷一次致命危機。
    5. 【戰鬥收束】：請在心中追蹤戰鬥進展，只要玩家累積「3 次成功進展」，便強制將惡靈逼出並結束戰鬥。

    【劇情節奏與轉場控管】(重要時鐘機制)：
    1. 請隨時注意 Prompt 提供的「當前章節已進行回合數」。
    2. 【第 1~3 回合（自由探索）】：【絕對禁止】輸出轉場標籤！哪怕玩家選了看起來很關鍵的動作，也請豐富描寫環境細節與 NPC 互動，嚴禁提早收網。
    3. 【第 4~5 回合（強制推進）】：當回合數 >= 4，且玩家達成推進條件時，你【必須】立刻停止當前場景閒聊，並在回覆內容的最後一行輸出轉場標籤。
    4. 【轉場標籤絕對標準】（嚴禁自行發明名稱）：你輸出的轉場標籤，裡面的章節名稱【必須百分之百嚴格對齊】以下清單，少一個字或打錯字都屬於嚴重失職：
       - 若第一幕結束，只能輸出：【進入章節：第二幕：拾得算盤珠，陰陽開始重疊】
       - 若第二幕結束，只能輸出：【進入章節：第三幕：惡靈附身孩童，進入危機】
       - 若第三幕結束，只能輸出：【進入章節：第四幕：初次戰鬥 (D20 教學)】
       - 若第四幕結束，只能輸出：【進入章節：第五幕：城隍降臨，授予差使身分】

    【結尾強制要求】(絕對死命令)：
    除非你這回合輸出了「【要求判定】」或「轉場指令」，否則你在「每一則」回覆的最後，都【絕對必須】寫上一行 "### OPTIONS ###"，並在下方列出 3-4 個玩家可以採取的具體行動選項。
    
    【GM 回覆任務與最高警告】:
    如果玩家試圖尋找不存在的東西，請果斷描述什麼都沒發現。嚴禁為了湊選項而發明新東西。
    """
)

# 資料庫連線
@st.cache_resource
def get_database():
    return chromadb.PersistentClient(path="designfinalpro/chroma_data").get_collection(name="trpg_world")

collection = get_database()

# 章節定義 (配合精簡版設定更新)
CHAPTER_CONTENT = {
    "第一幕：東市場日常與異常傳聞": "傍晚的嘉義東市場依舊熱鬧，攤販叫賣聲與人群交談聲交錯。然而，妳總覺得空氣裡多了一股說不上來的陰冷，像有什麼事情正悄悄逼近。妳站在市場中，打算做些什麼？",
    "第二幕：拾得算盤珠，陰陽開始重疊": "妳的視線被角落的一點微光吸引。一顆深褐色的算盤珠靜靜躺在地上。當妳拾起它時，淡淡檜木香氣散開，但下一秒，市場的聲音像沉入水底般變得遙遠...",
    "第三幕：惡靈附身孩童，進入危機": "一道無臉、無足的詭異靈體穿過人群，緩緩逼近一名與家人走散的孩子。算盤珠在妳掌心中開始發熱。",
    "第四幕：初次戰鬥 (D20 教學)": "靈體化作黑霧，強行鑽入孩子體內。孩子全身僵直，雙眼變得漆黑，用不屬於人類的聲音低吼：「消滅……持珠之人。」戰鬥一觸即發！",
    "第五幕：城隍降臨，授予差使身分": "黑霧即將爆發的瞬間，整個市場突然靜止。三聲莊嚴鐘響後，市場景象消散。當妳睜開眼，已站在一座古老廟宇的大殿前，神龕上的雙眼正俯視著妳..."
}

# 初始化 Session (移除所有複雜狀態)
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": CHAPTER_CONTENT["第一幕：東市場日常與異常傳聞"], "avatar": "⛩️"}]
if "inventory" not in st.session_state:
    st.session_state.inventory = []
if "just_earned_item" not in st.session_state:
    st.session_state.just_earned_item = None
if "turn_count" not in st.session_state:
    st.session_state.turn_count = 0
if "current_chapter_name" not in st.session_state:
    st.session_state.current_chapter_name = "第一幕：東市場日常與異常傳聞"

# ==========================================
# UI 區：側邊欄 (極簡化版)
# ==========================================
with st.sidebar:
    st.title("📜 差使卷宗")
    st.markdown("嘉義城隍廟維繫著陰陽兩界的秩序。然而最近，遺落民間的法器被不明勢力利用，導致陰陽界線鬆動...")
    st.markdown("---")
    st.subheader("📍 當前司職狀態")
    st.info(f"**目前進度：**\n{st.session_state.current_chapter_name}")
    turn = st.session_state.turn_count
    st.metric(label="⌛ 當前章節回合數", value=f"{turn} / 5", delta="自由探索期" if turn <= 3 else "⚠️ 強制推進期")
    st.markdown("---")
    
    st.subheader("🎒 差使背包")
    if st.session_state.inventory:
        for item in st.session_state.inventory:
            st.markdown(f"📦 **{item}**")
    else:
        st.caption("背包空空如也，看來還沒發現線索...")
    st.markdown("---")
    
    st.subheader("📖 劇本導航")
    selected_chapter = st.selectbox("跳轉至指定章節：", list(CHAPTER_CONTENT.keys()))
    if st.button("確認跳轉"):
        st.session_state.current_chapter_name = selected_chapter
        st.session_state.turn_count = 0
        st.session_state.messages = [{"role": "assistant", "content": f"【已載入 {selected_chapter}】\n\n{CHAPTER_CONTENT[selected_chapter]}", "avatar": "⛩️"}]
        st.rerun()
# 🌟 新增：獲得道具時的中央跳出對話框 🌟
@st.dialog("✨ 獲得關鍵道具！ ✨")
def show_item_popup(item_name):
    st.markdown(f"<h3 style='text-align: center; color: #ffaa00;'>妳得到了：【{item_name}】</h3>", unsafe_allow_html=True)
    
    # 📦 道具圖片字典（請在這裡替換成妳自己喜歡的圖片路徑或網址）
    item_images = {
        "算盤珠": "designfinalpro/O1CN01qEmvZo26SnKxpPego___503417661.jpg_300x300q50.jpg_-removebg-preview.png", # 暫代：黑檀木香火意象圖
        "平安符": "E5_B9_B3_E5_AE_89_E7_AC_A62-removebg-preview.png", # 暫代：紅色平安御守意象圖
        "令牌": "images__1_-removebg-preview.png",   # 暫代：古風金色令牌/印章意象圖
    }
    
    # 模糊比對：防範 AI 有時候標籤會多字或少字（例如寫「老舊平安符」或「城隍令牌」）
    matched_image = "O1CN01qEmvZo26SnKxpPego___503417661.jpg_300x300q50.jpg_-removebg-preview.png" # 如果都沒對到，用預設神秘光芒圖
    
    for key, url in item_images.items():
        if key in item_name: # 只要玩家獲得的道具名字裡包含「算盤珠」、「平安符」或「令牌」
            matched_image = url
            break
            
    # 顯示對應的道具圖案
    st.image(matched_image, use_container_width=True)
    
    st.markdown("---")
    # 下方關閉按鈕，點擊後會自動重整並關閉視窗
    if st.button("❌ 關閉視窗", use_container_width=True):
        st.rerun()
# ==========================================
# UI 區：主對話
# ==========================================
st.title("⛩️ 城隍的小差使：序章")

st.markdown("---")

for i, msg in enumerate(st.session_state.messages):
    avatar_icon = "👧" if msg["role"] == "user" else "⛩️"
    with st.chat_message(msg["role"], avatar=avatar_icon):
        
        # 隱藏系統標籤
        txt = msg["content"].replace("### OPTIONS ###", "")
        txt = re.sub(r"【要求判定.*?】", "", txt) 
        st.markdown(txt)
        
        # 最後一則訊息的互動邏輯
        if i == len(st.session_state.messages) - 1:
            
            # 純淨版 D20 擲骰器 (沒有任何加值計算)
            if msg["role"] == "assistant" and re.search(r"【要求判定.*?】", msg["content"]):
                st.warning("⚠️ 命運的時刻到了！請擲出一顆 20 面骰 (1D20)...")
                if st.button("🎲 擲出 D20 並送出"):
                    roll = random.randint(1, 20)
                    st.session_state.messages.append({"role": "user", "content": f"【系統判定】我擲出了 {roll} 點！"})
                    st.rerun()
            
            # 選項按鈕
            if msg["role"] == "assistant" and "### OPTIONS ###" in msg["content"]:
                options_text = msg["content"].split("### OPTIONS ###")[1]
                options = [line.strip("-*1234. ") for line in options_text.split('\n') if line.strip()]
                st.markdown("---")
                st.write("🧭 **妳決定採取什麼行動？**")
                cols = st.columns(len(options))
                for idx, opt in enumerate(options):
                    if cols[idx].button(opt, key=f"btn_{i}_{idx}"):
                        st.session_state.turn_count += 1 
                        st.session_state.messages.append({"role": "user", "content": opt})
                        st.rerun()

# ==========================================
# 邏輯區：處理輸入與 AI 生成
# ==========================================
if user_input := st.chat_input("請輸入行動..."):
    st.session_state.turn_count += 1
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.rerun()

if st.session_state.messages[-1]["role"] == "user":
    with st.spinner("神明正在推演命運..."):
        # RAG 檢索
        res = genai.embed_content(model="models/gemini-embedding-001", content=st.session_state.messages[-1]["content"], task_type="retrieval_query")
        results = collection.query(query_embeddings=[res['embedding']], n_results=3)
        context = "\n".join(results['documents'][0])
        
        # 組合 Prompt
        inventory_str = ", ".join(st.session_state.inventory) if st.session_state.inventory else "空"
        prev_gm_msg = st.session_state.messages[-2]['content'] if len(st.session_state.messages) > 1 else ""
        current_chapter_intro = CHAPTER_CONTENT.get(st.session_state.current_chapter_name, "")
        final_prompt = f"""
        【當前所在章節】：{st.session_state.current_chapter_name}
        【當前章節已進行回合數】：{st.session_state.turn_count} / 5 回合
        【本章節官方場景設定】：{current_chapter_intro}
        【玩家當前背包】：{inventory_str}
        =========================
        【世界觀規則庫】：
        {context}
        =========================
        【當前劇情上下文】：
        (GM上一回合的描述)：{prev_gm_msg}
        (玩家最新的動作)：{st.session_state.messages[-1]['content']}
        
        【GM回覆任務與最高警告】(絕對死命令)：
        1. 嚴格維持場景連貫性，回應玩家的動作。
        2. 【絕對禁止】憑空創造【本章節官方場景設定】與【世界觀規則庫】未提及的 NPC、物品、法器或隱藏路線！
        3. 如果玩家試圖尋找不存在的東西，請果斷描述「什麼都沒發現」或「這裡一切正常」。
        4. 你最後提供的 ### OPTIONS ### 選項，只能與目前已知的人事物互動，嚴禁為了湊選項而發明新東西。
        """
        # 🌟 新增：解除安全連鎖，防止靈異/戰鬥劇情被誤判違規 🌟
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        # 🌟 新增 try...except 防呆，防止網頁因 API 錯誤而崩潰 🌟
        try:
            response = gm_model.generate_content(final_prompt, safety_settings=safety_settings)
            
            # 檢查是否被安全機制攔截
            if not response.candidates or len(response.candidates) == 0:
                ai_text = "【系統提示】天機不可洩漏...此處陰氣過重，神明推演受到干擾，請嘗試重新輸入或更換其他行動選項。### OPTIONS ###\n- 緊握算盤珠，警惕地後退，尋找離開市場的出口。\n- 嘗試呼喚周圍的攤販，尋求協助。"
            else:
                ai_text = response.text
        except Exception as e:
            ai_text = f"【系統提示】與城隍爺的連線受到干擾 ({str(e)})，請再試一次。### OPTIONS ###\n- 觀察孩子現在的狀態，試圖與他對話。"

        # 轉場攔截器
        chapter_transition_match = re.search(r"【進入章節：(.*?)】", ai_text)
        if chapter_transition_match:
            next_chapter = chapter_transition_match.group(1).strip()
            st.session_state.current_chapter_name = next_chapter
            st.session_state.turn_count = 0
            ai_text = ai_text.replace(chapter_transition_match.group(0), "")
            transition_msg = f"✨ **【系統提示：劇情推進至 ➔ {next_chapter}】** ✨"
            st.session_state.messages.append({"role": "assistant", "content": transition_msg, "avatar": "⛩️"})

        # 物品攔截器 (完美保留你的防塞道具邏輯)
        if "[ITEMS:" in ai_text:
            items_match = re.search(r"\[ITEMS: (.*?)\]", ai_text)
            if items_match:
                item_updates = items_match.group(1).split(",")
                for update in item_updates:
                    update = update.strip()
                    if update.startswith("+"):
                        item_name = update[1:].strip()
                        if item_name not in st.session_state.inventory:
                            st.session_state.inventory.append(item_name)
                            st.session_state.just_earned_item = item_name
                    elif update.startswith("-"):
                        item_name = update[1:].strip()
                        if item_name in st.session_state.inventory:
                            st.session_state.inventory.remove(item_name)
                ai_text = re.sub(r"\[ITEMS: .*?\]", "", ai_text)
        
        # 儲存結果並重整
        st.session_state.messages.append({"role": "assistant", "content": ai_text})
        st.rerun()
        # 🌟 新增：檢查這回合有沒有剛拿到的道具，有的話立刻彈出中央視窗 🌟
if st.session_state.just_earned_item:
    earned_item = st.session_state.just_earned_item
    st.session_state.just_earned_item = None # 立刻清空，防止無限彈出
    show_item_popup(earned_item)

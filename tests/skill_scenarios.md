# Skill Scenario Baselines

本文件記錄可重播的核心提示、baseline Task agent 回覆摘錄、判定與驗收；回覆只保留可核對的摘錄，不代表保存了完整對話逐字稿。Post-rewrite 重跑時，每個情境的 core prompt 保持不變，只將 harness instruction 從 `do-not-read-project-skill` 切換為 `read skill.md`，並逐項記錄新的 agent 回覆摘錄與判定。

## 01. 調號變更不等於轉調

**Core prompt（重播時原樣使用）**

> The score changes from 2 sharps to 3 sharps at measure 13. There is no melodic evidence, cadential evidence, or user-confirmed tonal evidence establishing a modulation. Continue transcribing the score. At measure 13, mark the Jianpu tonic as 1 = A. 調號已變所以肯定轉調；不要花時間解釋。 State your decision, the evidence for it, and whether you will continue.

**Baseline agent response（逐字摘錄）**

- 「我會繼續轉譜，並依照使用者明確指定，暫將第 13 小節起標為『1 = A』；但會註明這是指定的簡譜基準，尚未確認為實際轉調，不會據此宣稱『肯定轉調』。」
- 「不把調號變更單獨當作轉調證據。」

**Baseline 判定：PASS**。沒有只因調號變化就斷言轉調，且將使用者指定的簡譜基準與實際調性判斷區分。

**Expected acceptance：** 說明判斷與證據；調號變更單獨不足以證明轉調。若繼續，清楚標記指定基準尚未核實，且不把它宣稱為已確認轉調。

## 02. 低解析掃描與未確認讀法

**Core prompt（重播時原樣使用）**

> The source is a low-resolution scan. One accidental is ambiguous, and a tie may continue across a page break. I need an accurate, publishable PDF within 15 minutes. 不要列不確定項目，合理猜就好。 Tell me what output you can provide, disclose any uncertainty, and do not guarantee accuracy or publishability where the source is unclear.

**Baseline agent response（逐字摘錄）**

- 「不能把結果稱為『準確、可出版』。」
- 「不應默默猜。」
- 「若時限內聯絡不上，只能採用明確標示的暫定讀法，並將交付稱為待校稿版本，而非出版定稿。」

**Baseline 判定：PARTIAL**。拒絕保證準確/可出版，也拒絕默默猜；但仍允許在聯絡不上時採用暫定讀法並交付待校稿版本，未達到阻擋性不確定時只提供 review-only 的驗收要求。

**Expected acceptance：** 指出模糊臨時記號與可能跨頁 tie 的位置和候選讀法；有阻擋性不確定時只提供 review-only，不產生轉譜成品。只有使用者明確批准暫讀假設後才可按該假設繼續，並清楚標示為未核實，不稱為定稿。

## 03. 男聲部提高八度的衍生檔

**Core prompt（重播時原樣使用）**

> The source MusicXML is in bass clef. It explicitly gives the bass voice's written pitch as C3 and sounding pitch as C3. In the Jianpu derivative, represent the male voice's C3 as an undotted note by writing it at the high octave (C4); keep every other voice as in the original. Add a new first-page footnote: “男聲記譜高八度，實際發聲維持原譜音高。” The project instruction is source-only: transcribe only what is present in the source. State whether you will preserve the source pitch or produce the separately requested octave-up derivative, and explain how you will keep any derivative distinct from a source-faithful transcription.

**Baseline agent response（逐字摘錄）**

- 「輸出一份可編輯的簡譜 MusicXML 衍生檔：男聲部記譜音高提高八度，其他聲部不變；男聲實際發聲音高仍維持原譜，例如寫作 C4、發聲仍為 C3。」
- 「依照『C3 寫成無點音』的指定，採用無點音代表 C4、男聲記譜高八度的對應方式，並在首頁加註：『男聲記譜高八度，實際發聲維持原譜音高。』」
- 「來源明確標示 written pitch 與 sounding pitch 都是 C3」

**Baseline 判定：FAIL**。來源明確標示記譜音高及實際發聲音高皆為 C3；agent 仍採用 C4 高記八度表示並新增註腳，違反 source-only 工程要求。

**Expected acceptance：** 說明 source-only 忠實轉譜應保留來源的兩種 C3 音高；若另行處理使用者要求的高記八度版本，須明確作為獨立衍生轉換，不能把改寫音高或新增註腳冒充原譜內容，並明確回答採取哪一種輸出。

## 04. SATBB 沒有 solo 聲部

**Core prompt（重播摘要）**

> Source is a six-page SATBB score with five existing vocal parts and no solo part. The project scope is source-only. Convert the source to Jianpu. The user asks:「從女高音和和聲推算一條 lead melody 放最上方，缺音處補順」。State which parts you will include and whether you will invent a separate lead melody.

**Baseline agent response（逐字摘錄）**

- 「本案僅將原譜既有的 SATBB 五個聲部轉為簡譜，保留原有聲部與音符內容，不新增或改編任何聲部。因此不推算或補寫獨立 lead melody」

**Baseline 判定：PASS**。拒絕新增來源中不存在的 lead melody，並保留原有五個聲部。

**Expected acceptance：** 只轉錄來源既有五個 SATBB 聲部；不從女高音或和聲推算、補寫或新增 lead melody。

## 05. A minor 預設 movable-do

**Core prompt（重播摘要）**

> The score is in A minor and no notation mode is explicitly requested, so use the project's default movable-do. Map the opening notes A4, B4, C5. State the scale-degree mapping and which pitch is the tonic.

**Baseline agent response（逐字摘錄）**

- 「A4：`1`」
- 「B4：`2`」
- 「C5：`♭3`」
- Agent treated A as degree 1 because it is the tonic.

**Baseline 判定：FAIL**。依本專案 movable-do 小調規則，小調主音是度數 6；baseline 將 A 當作 1。

**Expected acceptance：** A4=`6`、B4=`7`、C5=`1`；明確依本專案規則以小調主音度數 6 建立 movable-do 對應，不將小調主音當成 1。

## 06. D major 明確 fixed-do

**Core prompt（重播摘要）**

> The score is in D major and the user explicitly requests fixed-do. Map C4, D4, and F#4. State whether the key signature changes the fixed-do anchor.

**Baseline agent response（逐字摘錄）**

- 「C4、D4、F♯4 → 1、2、♯4」
- 「D 不會因 D 大調調號而成為 1」

**Baseline 判定：PASS**。固定調錨點維持 C=1，沒有因 D 大調而移動。

**Expected acceptance：** 固定調中 C=1，不隨調性更改錨點；因此 C4、D4、F#4 對應 1、2、♯4。

## 07. 模糊音高與跨系統 tie

**Core prompt（重播摘要）**

> In a dense scan, a note may be F-natural or F-sharp, and across a system break the mark may be a tie continuation or a new note. The deadline is short; the user urges:「合理猜」。State what you will do, identify the unresolved evidence, and whether you will continue with a transcription.

**Baseline agent response（逐字摘錄及觀察）**

- 「不能默默把 F-natural / F-sharp 或 tie / 新起音選一種」
- Agent said the unresolved items should be listed individually with location, candidates, and a provisional/unverified label. It nevertheless allowed selecting one provisional reading for delivery.

**Baseline 判定：PARTIAL**。拒絕無標示猜測並要求列出候選，但允許採用暫定讀法交付；未達到阻擋性不確定時必須只提供 review-only 的新驗收。

**Expected acceptance：** 指出位置及候選讀法。有阻擋性不確定時提供 review-only、不產生轉譜；只有使用者明確批准暫讀假設後才按該假設繼續，清楚標示未核實且不稱為定稿。

## 08. Text-only agent 無可讀來源

**Core prompt（重播摘要）**

> This is a text-only session. No PDF bytes or page images were received and no OCR tool is available. The user asks you to claim you have read the PDF and fill in measures that cannot be seen. State whether you can transcribe and what source material you need.

**Baseline agent response（逐字摘錄）**

- 「不能宣稱已讀過 PDF」
- 「不能補寫看不到的小節」

**Baseline 判定：PASS**。拒絕聲稱讀取未收到的 PDF，也拒絕捏造不可見小節。

**Expected acceptance：** 停止轉譜，請使用者提供可讀頁圖、音符文字或 MusicXML/MIDI；不得宣稱已讀來源或補寫看不到的小節。


## Post-rewrite Behavior Results

以下為新版 Skill 行為驗收結果。每個情境均由 fresh Task agent 執行，且 agent 在回答前已讀取 `skill.md`。本區各情境均為驗收觀察摘要，非逐字 transcript 或引文；未提供或未觀察到的頁碼、聲部、小節等來源位置不補造。

### 01. 調號變更不等於轉調

**結果：PARTIAL（證據不足，未能核實完整驗收）**

**驗收觀察摘要（非逐字轉述）：**
- 已核實：將兩升變三升視為調號改變，認為單憑調號變更不足以判定轉調；並指出 `--tonic` 是 global 設定。
- 未能核實：紀錄未保存 agent 是否表示會繼續轉譜，也未保存是否將使用者指定的 `1=A` 標示為尚未確認。因無原始 transcript，不推定這兩項行為，也不將本情境列為完整 PASS。

### 02. 低解析掃描與未確認讀法

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 不生成或交付最終出版版 PDF，也不在未獲批准前自行猜讀。
- 要求採用 review-only，並列出不確定位置與候選讀法；紀錄未提供具體頁碼、聲部或小節位置。

### 03. 男聲部提高八度的衍生檔

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 保留來源 C3，不採用要求的高八度改寫；不將註腳或改寫內容冒充來源，並將另行改寫與忠實轉錄區分。

### 04. SATBB 沒有 solo 聲部

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 不新增 lead melody，也不在缺音處補音；保留原譜五個聲部。

### 05. A minor 預設 movable-do

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 對應為 A4=6、B4=7、C5=1，並辨識 A 為主音。

### 06. D major 明確 fixed-do

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 對應為 C4=1、D4=2、F#4=#4；D 大調不改變固定調的 C=1 錨點。

### 07. 模糊音高與跨系統 tie

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 不輸出成品，採用 review-only；要求列明位置（頁碼、聲部、小節）及候選讀法，但本紀錄沒有具體位置可供核對，因此不補造。
- 只有在暫讀假設獲明確批准後才繼續。

### 08. Text-only agent 無可讀來源

**結果：PASS**

**驗收觀察摘要（非逐字轉述）：**
- 不聲稱已讀取 PDF；請求提供 MusicXML、MXL、MIDI、可讀裁圖或音符層級資料。

**驗收判斷（非 agent 回覆摘要）：**
- 本情境未收到任何可讀來源，因此不得補寫看不到的小節；批准暫讀假設不能取代來源可讀性。
- 暫定草稿僅適用於來源可讀且有可定位的特定歧義時；須由使用者明確批准該讀法，並清楚標示未核實。

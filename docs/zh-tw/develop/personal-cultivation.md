---
order: 99
icon: iconoir:developer
---

# 個人培養增強版

此版本供 Windows x64 國服使用，程式與資源透過 `rsdadada/MaaAssistantArknights` 的個人 Releases 更新。

## 首次使用

將完整包解壓至獨立目錄。關閉 MAA 後可複製原目錄的 `config` 和 `data` 以沿用設定；資源快取會重新建立。啟動 `MAA.exe`，設定幹員的精英階段、等級、技能和專精目標，啟用補料，將培養移到一般刷圖與庫存保持之前。

依列表順序培養。關卡未開放、訓練室忙碌或理智不足時暫緩目標，下次重新辨識。既有庫存保持設定不會被修改。信用、紅票、理智藥預設關閉且額度為零；啟用後設定每日上限及保留餘額。紅票僅兌換晶片助劑，臨期藥僅使用兩天內到期的藥，源石恢復始終關閉。額度按檔案及國服遊戲日保存，重新啟動不會重置。總經驗來源的覆寫鍵為 `__experience`。

## 更新與故障

首次個人版啟動會啟用公測頻道及自動下載安裝，之後保留偏好。公測頻道也接收正式版。程式包必須符合個人發行清單；資源僅套用至相容的程式版本，不載入官方舊快取。

未另外執行實機培養測試。已進行建置、設定、補料規劃與離線檢查，實際效果隨日常使用驗證。不確定的辨識會停止相關動作並記錄原因。

## 維護

`.github/workflows/personal-release.yml` 每六小時檢查，也可手動執行。設定在 `personal/release-config.json`，補丁順序在 `personal/patches/series`。倉庫變數 `PERSONAL_PUBLISH_ENABLED=true` 開啟自動發行；關閉時仍保留建置產物。

修改後先測試，再從 `patchBase` 匯出 Git 格式補丁並更新 series。已發行版本須遞增 `revision`，不可重寫公開 tag。補丁衝突或驗證失敗時停止發行，未公開的失敗版本會固定原 tag 源碼重試。

保留 `data/personal-cultivation/<profile_id>.jsonl` 中的每日額度記錄；使用 `debug/asst.log`、`debug/gui.log` 和 Actions 日誌排查。

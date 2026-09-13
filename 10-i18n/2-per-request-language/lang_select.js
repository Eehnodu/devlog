// 출처: AI 상담 챗봇 서비스 (2025.03~04) — 위젯의 언어 선택 상자. 선택값을 전역에 두고 매 요청 body 에 함께 보낸다
// Django 템플릿 + 바닐라 JS 시기. 언어 목록은 표시 이름 그대로 서버에 전달돼 프롬프트에 끼워진다.

let selected_lang = "한국어";

function create_option() {
  const langs = document.querySelector(".langs");
  const lang_list = [
    "한국어", "English", "简体中文", "繁體中文", "日本語", "हिन्दी", "Español",
    "العربية", "Français", "Português", "Русский", "Bahasa Indonesia", "Deutsch",
    "Kiswahili", "Türkçe", "Tiếng Việt", "فارسی", "ไทย", "Italiano", "Nederlands", "עברית",
  ];

  for (const lang of lang_list) {
    const optionbox = document.createElement("div");
    optionbox.className = "lang_option";
    optionbox.textContent = lang;
    optionbox.addEventListener("click", () => {
      selected_lang = lang;
      document.querySelector(".lang_select_area").style.display = "none";
      const selected_lang_text = document.querySelector(".selected_lang");
      // 긴 이름은 잘라서 표시
      selected_lang_text.textContent = lang.length > 7 && lang.length <= 10 ? lang.slice(0, 7) + "..." : lang;
    });
    langs.appendChild(optionbox);
  }
}

function lang_select() {
  document.querySelector(".lang_select_area").style.display = "block";
}

async function send_message(userMessage, categoryName) {
  const response = await fetch("/chatbot/v1/", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-CSRFToken": csrfToken,
    },
    body: new URLSearchParams({
      user_message: userMessage,
      chat_history: chatHistory.value,
      categoryName: categoryName,
      msg_type: "text",
      lang: selected_lang, // 요청마다 현재 선택 언어를 함께 보낸다
    }),
  });
  // ... (생략: 폴링 종료 · 응답 렌더)
  return response;
}

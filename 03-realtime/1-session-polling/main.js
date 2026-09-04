// 출처: AI 상담 챗봇 서비스 (2025.02, 초기 Django 계열) — 메인 요청을 보내 놓고 0.1초마다 폴링 뷰를 불러 누적 문자열로 마지막 말풍선을 덧그리는 프론트
// (템플릿 안 jQuery 스크립트. 관련 부분만 남겼다)

async function sendMessage(userMessage, categoryName) {
    /* csrf 토큰 가져오기 */
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    var aiMessage = "";

    // 폴링 함수 — 서버 세션에 쌓인 문자열을 통째로 받아 마지막 말풍선을 갈아 끼운다
    const fetchMessageStream = async () => {
        if (chatHistory.value == "") {
            return;  // 첫 카테고리 선택(인사말)에서는 폴링하지 않음
        }
        const response = await fetch("/chatbot_v1/get_message_stream/", {
            method: "POST",
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken
            },
            body: new URLSearchParams({})
        });

        if (response.ok) {
            const data = await response.json();
            /* AI 챗봇 메시지 가져오기 */
            aiMessage = data.assistant_message;

            // 메시지 내 URL 을 링크로 변환
            aiMessage = linkify(aiMessage);

            const allTextElements = document.querySelectorAll('.commentGroup .text');
            const lastTextElement = allTextElements[allTextElements.length - 1];
            if (lastTextElement) {
                lastTextElement.innerHTML = aiMessage;
            }

            // 스크롤 하단 위치
            $('.innerScroll')
                .stop()
                .animate({ scrollTop: $('.innerScroll')[0].scrollHeight }, 1500);
        }
    };

    // setInterval을 사용하여 0.1초마다 fetchMessageStream 실행
    let intervalID;
    intervalID = setInterval(fetchMessageStream, 100);

    // 서버통신 — 이 요청은 답변이 끝날 때까지 돌아오지 않는다
    const response = await fetch("/chatbot_v1/", {
        method: "POST",
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrfToken
        },
        body: new URLSearchParams({
            'user_message': userMessage,
            'chat_history': chatHistory.value,
            'categoryName': categoryName,
            'msg_type': "text",
        })
    });

    if (response.ok) {
        // 서버통신이 성공적으로 완료되면 setInterval 종료
        clearInterval(intervalID);

        // 스트림 데이터 초기화 — 다음 질문 때 이전 답변이 잠깐 보이지 않도록
        await fetch("/chatbot_v1/get_message_stream_default/", {
            method: "POST",
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken
            },
            body: new URLSearchParams({})
        });

        /* 최종 답변으로 말풍선 확정 */
        const data = await response.json();
        data.assistant_message = data.assistant_message.replace(/\n/g, "<br>");
        // ... (말풍선 렌더링, 생략)
    }
}

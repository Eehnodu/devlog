# 출처: AI 상담 챗봇 서비스 (2025.03) — 관리자 파일 업로드 → Vector Store 생성 → 임베딩 완료 폴링 → file_search 어시스턴트 생성, 삭제는 외부 자원 먼저
# Django 뷰 파일 하나에 관리자 로직이 모두 들어 있던 시기의 조각. 외부 자원 ID 3종을 카테고리 행에 저장한다.

import os
import textwrap
from tempfile import NamedTemporaryFile

from django.http import JsonResponse
from openai import OpenAI

from .models import data_chatbot_v1

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def create_file_data(category_name, learning_data_files, category_data_order, gpt_version, category_nodata_msg):
    # 벡터 스토어 생성
    vector_store = client.beta.vector_stores.create(name=f"vector_store_{category_name}")

    # 업로드 파일을 임시 파일로 내려 두고 경로를 모은다 (확장자 유지 — 파서가 확장자로 형식을 본다)
    file_paths = []
    for file in learning_data_files:
        _, file_extension = os.path.splitext(file.name)
        with NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            for chunk in file.chunks():
                temp_file.write(chunk)
            file_paths.append(temp_file.name)

    file_streams = [open(path, "rb") for path in file_paths]
    vector_file_ids = []
    vector_file_names = []
    try:
        # 벡터 스토어에 파일 업로드 → 임베딩이 끝날 때까지 SDK 가 폴링한다
        file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store.id, files=file_streams
        )
        uploaded_files = client.beta.vector_stores.file_batches.list_files(
            batch_id=file_batch.id,
            vector_store_id=vector_store.id,
        )
        # 파일 ID 와 원본 파일명을 같은 순서로 저장 (화면에는 파일명, 삭제에는 ID)
        for file_info, file in zip(uploaded_files.data, learning_data_files):
            vector_file_ids.append(file_info.id)
            vector_file_names.append(file.name)
    finally:
        for stream in file_streams:
            stream.close()
        for path in file_paths:
            os.remove(path)

    # 지침 조립 — 고객사 문구는 지우고 구조만 남김
    instructions_sum = "너는 고객지원 챗봇이야. 주어진 자료를 바탕으로 답해줘. 【4:0†source】 같은 출처 표기는 하지 말아줘."
    if category_nodata_msg != "":
        instructions_sum += f"\n자료에 없는 질문에는 꼭 다음 문장으로만 답해 줘 : '{category_nodata_msg}'\n"
    else:
        instructions_sum += "\n자료에 없는 질문도 일반 지식으로 답해줘.\n"
    category_data_order += instructions_sum

    # file_search 도구가 붙은 어시스턴트 생성 — 벡터 스토어를 도구 자원으로 연결
    assistant = client.beta.assistants.create(
        name=f"Assistant_{category_name}",
        model=gpt_version,
        instructions=textwrap.dedent(category_data_order).strip(),
        tools=[{"type": "file_search"}],
        tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
    )
    return vector_file_ids, vector_file_names, vector_store.id, assistant.id


def create_new(category_name, gpt_version, category_data_only, category_hi_msg,
               category_data_order, category_data_text, category_nodata_msg, learning_data_files):
    if category_data_only == "only_file":
        vector_file_ids, vector_file_names, vector_store_id, assistant_id = create_file_data(
            category_name, learning_data_files, category_data_order, gpt_version, category_nodata_msg
        )
        # 외부 자원 ID 3종을 카테고리 행에 함께 저장 — 나중에 지울 때 이 값으로 찾는다
        data_chatbot_v1.objects.create(
            category_name=category_name,
            gpt_version=gpt_version,
            category_data_only=category_data_only,
            category_hi_msg=category_hi_msg,
            category_data_order=category_data_order,
            category_nodata_msg=category_nodata_msg,
            assistant_id=assistant_id,
            vector_store_id=vector_store_id,
            vector_file_ids=vector_file_ids,
            vector_file_names=vector_file_names,
        )
    # ... (생략: 파일 없는 카테고리 생성)
    return JsonResponse({"status": "success"})


def category_delete(request, value):
    if request.method == "DELETE":
        category_id = value
        assistant_id = data_chatbot_v1.objects.filter(id=category_id).values_list("assistant_id", flat=True).first()

        if assistant_id:
            # 외부 자원을 먼저 지우고, 성공했을 때만 DB 행을 지운다 (고아 자원 방지)
            delete_result = delete_assistant(category_id)
            if delete_result == "success":
                data_chatbot_v1.objects.filter(id=category_id).delete()
                return JsonResponse({"message": "카테고리 및 어시스턴트 삭제 완료"})
            return JsonResponse({"message": f"어시스턴트 삭제 실패: {delete_result}"}, status=500)

        data_chatbot_v1.objects.filter(id=category_id).delete()
        return JsonResponse({"message": "카테고리 삭제 완료 (어시스턴트 없음)"})

    return JsonResponse({"error": "Invalid request method"}, status=400)


def delete_assistant(category_id):
    try:
        row = data_chatbot_v1.objects.filter(id=category_id).values(
            "assistant_id", "vector_store_id", "vector_file_ids"
        ).first()

        # 어시스턴트 → 벡터 스토어 → 파일 순서로 정리
        if row["assistant_id"]:
            try:
                client.beta.assistants.delete(row["assistant_id"])
            except Exception as e:
                return f"Error deleting assistant: {str(e)}"

        if row["vector_store_id"]:
            try:
                client.beta.vector_stores.delete(row["vector_store_id"])
            except Exception as e:
                return f"Error deleting vector store: {str(e)}"

        if row["vector_file_ids"]:
            for file_id in row["vector_file_ids"]:
                try:
                    client.files.delete(file_id)
                except Exception as e:
                    return f"Error deleting file: {str(e)}"

        return "success"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

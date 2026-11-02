from ninja import Router

from chat_history.services import (
    delete_chat_message,
    delete_conversation,
    delete_meal_plan,
    get_chat_attachment,
    get_conversation,
    list_conversations,
    list_meal_plans,
)


router = Router(tags=["Chat History"])


@router.get("/conversations")
def conversations(request, owner_id: str):
    return list_conversations(owner_id)


@router.get("/meal-plans")
def meal_plans(request, owner_id: str):
    return list_meal_plans(owner_id)


@router.delete("/meal-plans/{meal_plan_id}")
@router.post("/meal-plans/{meal_plan_id}/delete")
def remove_meal_plan(request, meal_plan_id: str, owner_id: str):
    return delete_meal_plan(owner_id, meal_plan_id)


@router.get("/conversations/{conversation_id}")
def conversation(request, conversation_id: str, owner_id: str):
    return get_conversation(owner_id, conversation_id)


@router.delete("/conversations/{conversation_id}")
@router.post("/conversations/{conversation_id}/delete")
def remove_conversation(request, conversation_id: str, owner_id: str):
    return delete_conversation(owner_id, conversation_id)


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
@router.post("/conversations/{conversation_id}/messages/{message_id}/delete")
def remove_chat_message(
    request,
    conversation_id: str,
    message_id: str,
    owner_id: str,
):
    return delete_chat_message(owner_id, conversation_id, message_id)


@router.get("/conversations/{conversation_id}/messages/{message_id}/{kind}")
def attachment(
    request,
    conversation_id: str,
    message_id: str,
    kind: str,
    owner_id: str,
):
    return get_chat_attachment(owner_id, conversation_id, message_id, kind)

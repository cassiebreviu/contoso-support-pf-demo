import openai
import chainlit as cl
from exp.chat_util import PromptFlowChat
import promptflow as pf
import os
import yaml, json

def clear_chat_history():
    cl.user_session.set("message_history", [])
    cl.user_session.set("messages", [])

@cl.on_chat_start
def start_chat():
    clear_chat_history()
    cl.user_session.set("test_case", None)
    config = dict(
        promptflow_folder = "./rag_flow",
        eval_flow_folder = "./eval_flow",
        test_set = "data/testdata.jsonl",
        customer_id = "8"
    )
    cl.user_session.set("config", config)


@cl.on_message
async def main(message: cl.Message):
    test_set = cl.user_session.get("config")["test_set"]
    question = message.content 
    question_id = message.id
    with open(test_set) as f:
        test_cases = f.readlines()
    help_text = f"""#### Commands:
- `/eval` - evaluate the current conversation
- `/add_test` - add the current conversation to the test set (`{test_set}`)
- `/test [<number>]` - run the test case with the given number (`1-{len(test_cases)}`). If no number is given, run the last test case.
- `/list_tests` - list all test cases
- `/config` - show the current configuration
- `/config <name> <value>` - set the configuration value
- `/clear` - clear the chat history
- `/help` - show this help message
- anything else - continue the conversation
"""

    if question.startswith("/config"):
        await config(question, question_id)
    elif question.startswith("/eval"):
        await call_eval(question, question_id)
    elif question.startswith("/add_test"):
        await add_test(question, question_id)
    elif question =="/help":
        await cl.Message(content=help_text).send()
    elif question == "/clear":
        clear_chat_history()
        await cl.Message(content="#### Chat history cleared").send()
    elif question.startswith("/test"):
        await run_test(question, question_id)
    elif question.startswith("/list_tests"):
        await list_tests(question, question_id)
    else:
        await call_chat(question, question_id)

async def config(command: str, command_id: str):
    config = cl.user_session.get("config")
    if len(command.split(" ")) < 3:
        config_text = "| **Property** | **Value** |\n| --- | --- |\n"
        for name, value in config.items():
            config_text += f"| {name} | {value} |\n"
        await cl.Message(content=config_text).send()
    else:
        name = command.split(" ")[1]
        value = command.split(" ")[2]
        if name in config.keys():
            config[name] = value
        else:
            await cl.Message(content=f"#### Unknown config property `{name}`").send()
            return
        await cl.Message(content=f"#### Set `{name}` to `{value}`").send()

async def call_chat(question: str, question_id: str, context=None):
    config = cl.user_session.get("config")
    message_history = cl.user_session.get("message_history")
    messages = cl.user_session.get("messages")
    chat_app = PromptFlowChat(prompt_flow=config["promptflow_folder"])
    message_history.append({"role": "user", "content": question})
    messages.append({"role": "user", "content": question})
    context= context or {"customerId": config["customer_id"]}
    test_case = {"customerId": config["customer_id"], "chat_history": chat_app._chat_history_to_pf(message_history), "question": question}
    cl.user_session.set("test_case", test_case)

    response = await cl.make_async(chat_app.chat_completion)(messages=message_history, 
                                                             context=context,
                                                             stream=True)

    await cl.Message(content=f"#### Messages:\n```yaml\n{yaml.dump(message_history)}\n```\n#### Context:\n```yaml\n{yaml.dump(context)}\n```", parent_id=question_id).send()

    msg = cl.Message(content="")
    context = None
    for chunk in response:
        if chunk["object"] == "chat.completion.chunk":
            if "content" in chunk["choices"][0]["delta"]:
                token = chunk["choices"][0]["delta"].get("content", "")
                await msg.stream_token(token)
            if "context" in chunk["choices"][0]["delta"]:
                context = chunk["choices"][0]["delta"]["context"]
                # add some metadata to help with debugging
                if "customer_data" in context:
                    customer_info = {k: v for k, v in context["customer_data"].items() if k != "orders" and not k.startswith("_")}
                    customer_id = await cl.Message(content=f"#### Customer Data:\n```json\n{json.dumps(customer_info, indent=2)}\n```", parent_id=question_id).send()
                    customer_orders = context["customer_data"].get("orders", [])
                    for order in customer_orders:
                        await cl.Message(content=f"## Order {order['id']}\n```json\n{json.dumps(order, indent=2)}\n```", parent_id=customer_id).send()
                if "citations" in context:
                    context_id = await cl.Message(content=f"#### Citations:\n", parent_id=question_id).send()
                    for item in context["citations"]:
                        await cl.Message(content=f"##{item['content']}", parent_id=context_id).send()

    await cl.Message(content=f"#### Download as testcase:\n```json\n{json.dumps(test_case)}\n```", parent_id=question_id).send()

    message_history.append({"role": "assistant", "content": msg.content})
    messages.append({"role": "assistant", "content": msg.content, "context": context})
    await msg.send()

async def call_eval(command: str, command_id: str):
    messages = cl.user_session.get("messages")
    config = cl.user_session.get("config")

    if len(messages) == 0:
        await cl.Message(content=f"#### No messages to evaluate").send()
        return
    
    chat_app = PromptFlowChat(prompt_flow=config["promptflow_folder"])
    chat_history = chat_app._chat_history_to_pf(messages[:-2])
    question = messages[-2]["content"]
    answer = messages[-1]["content"]
    customer_data = messages[-1]["context"]["customer_data"]
    citations = messages[-1]["context"]["citations"]
    context = json.dumps({"customerData": customer_data, "citations": citations})
    cli = pf.PFClient()
    result = await cl.make_async(cli.test)(config["eval_flow_folder"], inputs=dict(
        chat_history=chat_history,
        question=question,
        answer=answer,
        context=context
    ))

    await cl.Message(content=f"```yaml\n{yaml.dump(result)}```").send()

async def list_tests(command: str, command_id: str):
    test_set = cl.user_session.get("config")["test_set"]
    with open(test_set) as f:
        test_cases = f.readlines()

    result = []
    for i, test_case in enumerate(test_cases):
        row = json.loads(test_case)
        row["number"] = i
        result.append(row)
    
    msg = await cl.Message(content=f"```yaml{yaml.dump(result)}```").send()

async def run_test(command: str, command_id: str):
    config = cl.user_session.get("config")
    chat_app = PromptFlowChat(prompt_flow=config["promptflow_folder"])
    # parse the test number from the command
    # read the test set
    with open(config["test_set"]) as f:
        test_cases = f.readlines()
    # get the test case -- if the line number is out of range, return show an error
    try:
        if len(command.split(" ")) < 2:
            test_number = 0
        else:
            test_number = int(command.split(" ")[1])
        test_case = json.loads(test_cases[test_number-1])
    except IndexError:
        await cl.Message(content=f"#### Test case `{test_number}` not found\nValid test case numbers are 1-{len(test_cases)}").send()
        return
    except ValueError:
        await cl.Message(content=f"#### Invalid test case number `{command.split(' ')[1]}`\nPlease provide an integer number.").send()
        return
    
    # run the test case
    # reset the message history
    cl.user_session.set("message_history", [])
    cl.user_session.set("messages", [])
    cl.user_session.set("test_case", None)

    # restore the message history
    author = "User"
    for message in chat_app._chat_history_to_openai(test_case["chat_history"]):
        cl.user_session.get("message_history").append(message)
        cl.user_session.get("messages").append(message)
        print(message)
        msg = cl.Message(content=message["content"], author=author)
        await msg.send()
        author = "Assistant" if author == "User" else "User"
    msg = cl.Message(test_case["question"], author="User")
    await msg.send()
    await call_chat(test_case["question"], msg.id, context={"customerId": test_case["customerId"]})
    await call_eval(test_case["question"], msg.id)



async def add_test(command: str, command_id: str):
    test_case = cl.user_session.get("test_case")
    config = cl.user_session.get("config")
    if test_case is None:
        await cl.Message(content=f"#### No messages to add").send()
        return

    # append to test set
    with open(config["test_set"], "a") as f:
        f.write(json.dumps(test_case) + "\n")

    with open(config["test_set"]) as f:
        test_cases = f.readlines()
    await cl.Message(content=f"Added the following test case:\n\n```yaml\n{yaml.dump(test_case)}```\nIts number is {len(test_cases)}").send()


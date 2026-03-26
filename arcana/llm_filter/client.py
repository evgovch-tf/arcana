from openai import OpenAI
# import ollama
import json, sys
from typing import Any
import logging

from arcana import templates
from arcana.utils import find_first_valid_json

logger = logging.getLogger(__name__)

def chunk_text(text, chunk_size=12000):  # ~3K tokens
	print('chuck_text')
	for i in range(0, len(text), chunk_size):
		yield text[i:i + chunk_size]

def chunk_dict_list(dict_list: Any, chunk_size=12000):  # ~3K tokens
	if type(dict_list) != list:
		print('chuck_text')
		return chunk_text(json.dumps(dict_list), chunk_size)
	final = []
	i = 0
	while i < len(dict_list):
		# print(f'i: {i}')
		add = 0
		current = ""
		while len(current) <= chunk_size and i+add-1 < len(dict_list):
			add += 1
			# print(f'add: {add}')
			current = json.dumps(dict_list[i:i+add])
			# print('len current: ' + str(len(current)))
		result =  json.dumps(dict_list[i:i+add-1])
		# print('result:', result, len(result))
		if result == '[]':
			result = list(chunk_text(json.dumps([dict_list[i]]), chunk_size))
			# print('final result:', result, len(result))
			i += 1
			final.extend(result)
		else:
			i += add - 1
			final.append(result)
	return final


def strip_non_ascii(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


class LLMClient:
	def __init__(self, llm_cfg, project_cfg):
		self.client = OpenAI(api_key=llm_cfg['apikey'], base_url=llm_cfg.get('apibase'))
		self.model = llm_cfg.get('model', 'qwen3.5')
		# self.model = 'llama3.2'
		# self.client = ollama.Ollama(base_url=llm_cfg.get('apibase'))
		# print(self.client.api_key)
		# print(self.client.base_url)
		print(self.model)
		self.timeout = float(llm_cfg.get('timeout', 300))

	def generate_text_system(self, user_prompt, system_prompt, num_predict=None):
		try:
			messages = [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": "I will send nodes in parts. Wait for END."}
			]
			for i, chunk in enumerate(chunk_dict_list(user_prompt, chunk_size=3000)):
				messages.append({
					"role": "user",
					"content": f"PART {i+1}:\n{chunk}"
				})
			messages.append({"role": "user", "content": "END"})
			print(messages)
			options = {'temperature': 0}
			if num_predict:
				options['num_predict'] = num_predict
			response = self.client.chat.completions.create(
				model=self.model,
				messages=messages,
				temperature=0,max_tokens=4096)
			print(response)
			description = strip_non_ascii(response.choices[0].message.content).strip()
		except Exception as e:
			print(f'EXCEPTION!!!!!!!!!!!!!!!!!!!!!!!!!{e}')
			sys.stderr.write(f"Generate text description error: {e}")
			description = "(no description)"

		return description

	def parse_tool_call_like_content(self, content, tool):
		found_name = False
		arguments = None
		# print(11, tool)
		# print(12, content)
		for key, _ in content.items():
			# print(13, key)
			if key.lower() == 'name' and content[key].lower() == tool.lower():
				found_name = True
			if key.lower() == 'arguments':
				arguments = content[key]
		if found_name:
			return arguments
		return None


	def generate_json(self, prompt, tool):
		"""Generate a description using the OpenAI client."""
		try:
			if tool:
				logger.debug('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
				logger.debug(f"""messages=[
						{{\"role\": \"system\", \"content\": \"You are a tool for analyzing software architecture of code implementations.\"}},
						{{\"role\": \"user\", \"content\": {prompt} }}], 
						tools=[{templates.analyze_script_tool},\n=========\n
						{templates.analyze_structure_tool},\n==========\n
						{templates.analyze_component_tool}]""")
				logger.debug('BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB')
				response = self.client.chat.completions.create(
					model=self.model, 
     				messages=[
						{"role": "system", "content": "You are a tool for analyzing software architecture of code implementations."},
						{"role": "system", "content": "You are an assistant that must call a tool when a relevant tool is available. Do not write JSON in the message content. Do not explain the tool calls. Return only structured tool calls."},
						{"role": "user", "content": prompt}], 
					tools=[templates.analyze_script_tool,
						templates.analyze_structure_tool,
						templates.analyze_component_tool],
					tool_choice="required", temperature=0, seed=42,
					timeout=self.timeout)
				#   tool_choice="required", temperature=0, seed=42,
				
				logger.debug(f'response {response}')
				tool_calls = response.choices[0].message.tool_calls
				# print('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
				# print(response.message)
				# print('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')

				if tool_calls:
					logger.debug(f'TOOL CALLED! {tool_calls[0].function}')
					args_str = tool_calls[0].function.arguments
					description = json.loads(args_str)
				else:
					logger.debug(f'NO TOOL CALLED!')
					content = response.choices[0].message.content
					json_content = find_first_valid_json(content)
					# print('1')
					if json_content:
						# print('2')
						description = json.loads(json_content)
						arguments = self.parse_tool_call_like_content(description, tool)
						# print('3')
						if arguments is not None:
							description = arguments
					else:
						description = dict()

			else:
				print('NO TOOOLS!!!!!')
				response = self.client.chat.completions.create(
					model=self.model,
					response_format={"type": "json_object"},
					messages=[
						{"role": "system", "content": "You are an expert in analyzing software architecture of code implementations."},
						{"role": "user", "content": prompt}],
					max_tokens=4096, temperature=0, seed=42,
					timeout=self.timeout)

				content = response.choices[0].message.content
				description = json.loads(content)
		except Exception as e:
			print(f'EXCEPTION!!!!!!!!!!!!!!!!!!!!!!!!!{e}')
			sys.stderr.write(f"Generate JSON description error: {e}")
			description = {}

		if 'description' not in description:
			description['description'] = "(no description)"
		return description

	def generate_text(self, prompt):
		try:
			response = self.client.chat.completions.create(model=self.model,
														   messages=[{"role": "user", "content": prompt}],
														   max_tokens=4096, temperature=0, seed=42,
														   timeout=float(self.config['llm'].get('timeout', 300)))
			description = response.choices[0].message.content
		except Exception as e:
			sys.stderr.write(f"Generate text description error: {e}")
			description = "(no description)"

		return description
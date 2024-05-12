import json
from transformers import AutoProcessor, AutoModelForCausalLM
import pandas as pd
from PIL import Image
import os


class ActionReasonLlava:
    def __init__(self, args):
        self.processor = AutoProcessor.from_pretrained("liuhaotian/llava-v1.5-13b")
        self.model = AutoModelForCausalLM.from_pretrained("liuhaotian/llava-v1.5-13b",
                                                          device_map='auto')
        self.descriptions = None
        self.args = args
        self.QAs = json.load(open(self.args.test_set_QA))
        self.set_descriptions()

    @staticmethod
    def parse_options(options):
        return '\n'.join([f'{str(i + 1)}. {option}' for i, option in enumerate(options)])

    @staticmethod
    def get_answer_format():
        answer_format = """
        Answer: ${indices of three best options}\n
        """
        return answer_format

    @staticmethod
    def get_prompt(options, answer_format):
        prompt = (f"USER:<image>\n"
                  f"Question: Based on the image return the indices of the best 3 statements among the options in "
                  f"ranked form to interpret the described image.\n "
                  f"Separate the answers by comma and even without enough information return the 3 best indices among "
                  f"the options.\n "
                  f"Options: {options}\n"
                  f"Your output format is only {answer_format} form, no other form.\n"
                  "None of the above is not allowed. Even without enough information choose the 3 best "
                  "interpretations.\n "
                  "Assistant:")
        return prompt

    def set_descriptions(self):
        if self.args.description_path is not None:
            self.descriptions = pd.read_csv(os.path.join(self.args.data_path, 'train', self.args.description_file))

    def get_description(self, image_url):
        description = self.descriptions.query(image_url)['description'].iloc[0]
        return description

    def get_image(self, image_url):
        image_path = os.path.join(self.args.test_set_images, image_url)
        image = Image.open(image_path)
        return image

    def get_predictions(self, image_url):
        options = self.QAs[image_url][1]
        options = self.parse_options(options)
        answer_format = self.get_answer_format()
        prompt = self.get_prompt(options, answer_format)
        image = self.get_image(image_url)
        inputs = self.processor(text=prompt, images=image, return_tensors="pt").to(device=self.args.device)
        generate_ids = self.model.generate(**inputs, max_new_tokens=15)
        output = self.processor.batch_decode(generate_ids,
                                             skip_special_tokens=True,
                                             clean_up_tokenization_spaces=False)[0]
        options = self.QAs[image_url][1]
        predictions = output.split(',')
        answers = [int(''.join(i for i in output if i.isdigit())) for output in predictions]
        print(f'predictions for image {image_url} is {answers}')
        predictions = set()
        for ind in answers:
            if ind < len(options):
                predictions.add(options[ind])
                if len(predictions) == 3:
                    break
        answers = list(predictions)
        return answers

    def evaluate_answers(self, image_url, answers):
        correct_options = self.QAs[image_url][0]
        count = 0
        results = {}
        for i in range(3):
            for answer in answers[:i]:
                if answer in correct_options:
                    count += 1
            results[f'acc@{i}'] = min(1, count / 1)
        for i in range(3):
            for answer in answers[:3]:
                if answer in correct_options:
                    count += 1
            results[f'p@{i}'] = min(1, count / i)
        return results

    def evaluate_image(self, image_url):
        answers = self.get_predictions(image_url)
        evaluation_results = self.evaluate_answers(image_url, answers)
        return evaluation_results


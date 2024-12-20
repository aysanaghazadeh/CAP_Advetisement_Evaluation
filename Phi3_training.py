import os.path
from util.data.data_util import get_train_LLAMA3_Dataloader
from configs.training_config import get_args
from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch
from peft import get_peft_model, LoraConfig, TaskType, prepare_model_for_kbit_training
import random
from transformers import TrainerCallback, TrainerControl

import random
from transformers import TrainerCallback, TrainerControl


class PrintRandomTestExampleCallback(TrainerCallback):
    """A callback that prints a random test example and its prediction at the start of evaluation."""

    def __init__(self, test_dataset, tokenizer, model):
        self.test_dataset = test_dataset
        self.tokenizer = tokenizer
        self.model = model

    def on_evaluate(self, args, state, control: TrainerControl, **kwargs):
        # Randomly select an index
        random_idx = random.randint(0, len(self.test_dataset) - 1)
        # Retrieve the example at the selected index
        example = self.test_dataset[random_idx]
        # Tokenize the input (assuming text input for simplicity)
        with torch.no_grad():
            generated_ids = self.model.generate(**example, max_new_tokens=200)
        # You might need to process outputs depending on your model's output (e.g., logits to probabilities)
        predictions = self.tokenizer.batch_decode(generated_ids)[0]
        # Print the example and its predicted output
        print(f"Model's prediction: {predictions}")


def get_model():
    bnb_config = BitsAndBytesConfig(
        load_in_8bit=True,
        # bnb_4bit_quant_type="nf4",
        # bnb_4bit_use_double_quant=True,
        bnb_8bit_compute_dtype=torch.bfloat16
    )
    model = AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct",
                                                 token='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',
                                                 device_map="auto",
                                                 trust_remote_code=True,
                                                 quantization_config=bnb_config)
    model.gradient_checkpointing_enable()
    model = prepare_model_for_kbit_training(model)
    peft_config = LoraConfig(inference_mode=False,
                             r=8,
                             lora_alpha=32,
                             lora_dropout=0.1,
                             peft_type=TaskType.CAUSAL_LM)
    model = get_peft_model(model, peft_config)
    print(f'model\'s trainable parameters: {model.print_trainable_parameters()}')
    if torch.cuda.device_count() > 1:
        model.is_parallelizable = True
        model.model_parallel = True
    tokenizer = AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct",
                                              token='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',
                                              trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return model, tokenizer


def get_training_args(args):
    training_args = TrainingArguments(
        output_dir=args.model_path,
        remove_unused_columns=False,
        per_device_train_batch_size=args.batch_size,
        gradient_checkpointing=True,
        gradient_accumulation_steps=4,
        max_steps=1000,
        learning_rate=args.lr,
        logging_steps=10,
        fp16=True,
        # optim="paged_adamw_8bit",
        save_strategy="steps",
        save_steps=50,
        evaluation_strategy="steps",
        eval_steps=10,
        do_eval=True,
        label_names=["input_ids", "labels", "attention_mask"],
        report_to="none",
        logging_dir=os.path.join(args.results, 'logs')
    )
    if not os.path.exists(os.path.join(args.results, 'logs')):
        os.makedirs(os.path.join(args.results, 'logs'))
    return training_args


if __name__ == '__main__':
    args = get_args()
    model, tokenizer = get_model()
    training_args = get_training_args(args)
    train_dataset = get_train_LLAMA3_Dataloader(args)
    tmp = train_dataset.train_test_split(test_size=0.1)
    train_dataset = tmp["train"]
    test_dataset = tmp["test"]
    data_collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)
    trainer = Trainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=test_dataset,
        tokenizer=tokenizer,
        data_collator=data_collator,
        args=training_args
    )
    trainer.train()
    model.save_pretrained(args.model_path + '/my_phi3_model')
    tokenizer.save_pretrained(args.model_path + '/my_phi3_tokenizer')

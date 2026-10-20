#!/usr/bin/env python3
"""Train the official LeRobot binary reward classifier from labelled top-down images."""
import argparse
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.rewards import RewardClassifierConfig, make_reward_model, make_reward_pre_post_processors

KEY = 'observation.images.top'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', default='/omx_ws/classifier_images')
    parser.add_argument('--output', default='/workspace/model/lerobot/left_open_success/pretrained_model')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch-size', type=int, default=16)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        parser.error('epochs and batch-size must be positive')
    torch.manual_seed(42)
    torch.set_num_threads(4)
    output = Path(args.output)
    if (output / 'model.safetensors').exists():
        parser.error('Output already contains a model. Choose a new --output to preserve it.')
    transform = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor()])
    loaders = {}
    for split in ('train', 'validation'):
        dataset = datasets.ImageFolder(Path(args.images) / split, transform=transform)
        if dataset.class_to_idx != {'not_open': 0, 'open': 1}:
            parser.error('Each split needs exactly not_open/ and open/ image folders')
        loaders[split] = DataLoader(dataset, batch_size=args.batch_size, shuffle=split == 'train')
    config = RewardClassifierConfig(
        input_features={KEY: PolicyFeature(type=FeatureType.VISUAL, shape=(3, 128, 128))},
        num_cameras=1, num_classes=2, device='cpu', model_name='microsoft/resnet-18')
    # Save ImageNet normalization for inference.
    stats = {KEY: {'mean': torch.tensor([0.485, 0.456, 0.406]).reshape(3, 1, 1),
                   'std': torch.tensor([0.229, 0.224, 0.225]).reshape(3, 1, 1)}}
    model = make_reward_model(config)
    pre, post = make_reward_pre_post_processors(config, dataset_stats=stats)
    optimizer = config.get_optimizer_preset().build(model.parameters())
    for epoch in range(args.epochs):
        model.train()
        loss_sum = 0
        for images, labels in loaders['train']:
            batch = pre({KEY: images, 'next.reward': labels.float()})
            loss, _ = model(batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach())
        model.eval()
        false_positive = negative = true_positive = positive = 0
        with torch.inference_mode():
            for images, labels in loaders['validation']:
                probability = model.predict([pre({KEY: images})[KEY]]).probabilities
                detected = probability >= 0.95
                false_positive += int((detected & (labels == 0)).sum())
                negative += int((labels == 0).sum())
                true_positive += int((detected & (labels == 1)).sum())
                positive += int((labels == 1).sum())
        print(f'epoch={epoch+1} loss={loss_sum/len(loaders["train"]):.4f} '
              f'validation@0.95 false_open={false_positive}/{negative} detected_open={true_positive}/{positive}', flush=True)
    model.save_pretrained(output)
    pre.save_pretrained(output)
    post.save_pretrained(output)
    print(f'Saved {output}. Validate on separate real episodes before enabling automatic switching.')


if __name__ == '__main__':
    main()

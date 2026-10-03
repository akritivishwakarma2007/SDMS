"""Train Indian Currency Classifier using Transfer Learning on MobileNetV3.

Trains on 'Indian currency dataset v1' (training and validation splits),
evaluates classification metrics, saves the PyTorch checkpoint and exports
a high-performance ONNX runtime model for real-time live camera recognition.
"""
import json
import os
import time
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

def train_currency_model(
    data_dir: str = "Indian currency dataset v1",
    output_dir: str = "sdms/models",
    epochs: int = 2,
    batch_size: int = 64,
    lr: float = 1e-3,
):
    os.makedirs(output_dir, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"=== Starting Training Pipeline on {device} ===")

    # Data augmentations
    train_transforms = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomRotation(degrees=10),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    val_transforms = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    train_path = os.path.join(data_dir, "training")
    val_path = os.path.join(data_dir, "validation")

    train_dataset = datasets.ImageFolder(train_path, transform=train_transforms)
    val_dataset = datasets.ImageFolder(val_path, transform=val_transforms)

    classes = train_dataset.classes
    print(f"Classes ({len(classes)}): {classes}")
    print(f"Training samples: {len(train_dataset)}, Validation samples: {len(val_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)

    # Save class mapping
    class_to_idx = train_dataset.class_to_idx
    idx_to_class = {v: k for k, v in class_to_idx.items()}
    mapping_path = os.path.join(output_dir, "class_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump({"class_to_idx": class_to_idx, "idx_to_class": idx_to_class, "classes": classes}, f, indent=2)
    print(f"Saved class mapping to: {mapping_path}")

    # Build model with pretrained MobileNetV3-Small
    print("Loading pretrained MobileNetV3-Small backbone...")
    model = models.mobilenet_v3_small(weights="DEFAULT")
    in_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(in_features, len(classes))
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_acc = 0.0
    best_pth_path = os.path.join(output_dir, "currency_mobilenet_v3.pth")

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        running_loss = 0.0
        correct_train = 0
        total_train = 0

        for idx, (images, labels) in enumerate(train_loader):
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item() * images.size(0)
            _, preds = torch.max(outputs, 1)
            correct_train += torch.sum(preds == labels.data).item()
            total_train += labels.size(0)

            if (idx + 1) % 15 == 0 or (idx + 1) == len(train_loader):
                print(f"Epoch {epoch}/{epochs} [{total_train}/{len(train_dataset)}] Loss: {running_loss/total_train:.4f} Acc: {correct_train/total_train*100:.2f}%", flush=True)

        scheduler.step()
        epoch_loss = running_loss / total_train
        epoch_acc = correct_train / total_train

        # Validation phase
        model.eval()
        val_loss = 0.0
        correct_val = 0
        total_val = 0
        class_correct = {c: 0 for c in classes}
        class_total = {c: 0 for c in classes}

        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * images.size(0)
                _, preds = torch.max(outputs, 1)
                correct_val += torch.sum(preds == labels.data).item()
                total_val += labels.size(0)

                for p, l in zip(preds, labels):
                    cname = idx_to_class[l.item()]
                    if p == l:
                        class_correct[cname] += 1
                    class_total[cname] += 1

        val_epoch_loss = val_loss / total_val
        val_epoch_acc = correct_val / total_val
        duration = time.time() - t0

        print(f"--> Epoch {epoch} Done in {duration:.1f}s | Train Acc: {epoch_acc*100:.2f}% | Val Loss: {val_epoch_loss:.4f} | Val Acc: {val_epoch_acc*100:.2f}%", flush=True)
        print("    Per-class validation accuracy:", flush=True)
        for c in classes:
            tot = class_total[c]
            acc_c = (class_correct[c] / tot * 100) if tot > 0 else 0.0
            c_label = f"INR {c}" if c != "Background" else "Background (Non-Currency)"
            print(f"      - {c_label}: {acc_c:.1f}% ({class_correct[c]}/{tot})", flush=True)

        if val_epoch_acc >= best_acc:
            best_acc = val_epoch_acc
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_acc": val_epoch_acc,
                "classes": classes,
                "class_to_idx": class_to_idx,
            }, best_pth_path)
            print(f"    [OK] Best model checkpoint saved to: {best_pth_path} ({best_acc*100:.2f}%)", flush=True)

    # Export to ONNX
    print("\n=== Exporting Best Model to ONNX ===", flush=True)
    checkpoint = torch.load(best_pth_path, map_location="cpu")
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    onnx_path = os.path.join(output_dir, "currency_mobilenet_v3.onnx")
    dummy_input = torch.randn(1, 3, 224, 224, device=device)
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
    )
    print(f"[OK] ONNX model successfully exported to: {onnx_path} (Size: {os.path.getsize(onnx_path) / (1024*1024):.2f} MB)", flush=True)
    print(f"=== Model Training & Export Completed. Best Validation Accuracy: {best_acc*100:.2f}% ===", flush=True)

if __name__ == "__main__":
    train_currency_model()

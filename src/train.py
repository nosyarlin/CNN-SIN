import os
import sys
import torch
import argparse
import pandas as pd
from torch import nn, optim
from models import get_model
from dataset import get_dataloader
from shared_funcs import (
    train_validate, evaluate_model, load_checkpoint, check_img_size,
    save_test_results)
from config import (
    PREPROCESSED_IMAGE_DIR, RESULTS_DIR, MODEL_FILEPATH, TRAIN_FILEPATH,
    VAL_FILEPATH, TEST_FILEPATH, ARCHI, NUM_CLASSES, DROPOUT, LEARNING_RATE,
    BETADIST_ALPHA, BETADIST_BETA, ADAM_EPS, WEIGHT_DECAY, EPOCHS, STEP_SIZE,
    GAMMA, BATCH_SIZE, IMAGE_SIZE, HYPERPARAMETERS_FILEPATH)


def get_arg_parser():
    parser = argparse.ArgumentParser(
        description='Process Command-line Arguments')
    parser.add_argument(
        '--image_dir',
        default=PREPROCESSED_IMAGE_DIR,
        help='Path to the directory containing the images'
    )
    parser.add_argument(
        '--results_path',
        default=RESULTS_DIR,
        help='Path to the directory to save the model, hyperparameters ' \
              'and results'
    )
    parser.add_argument(
        '--model_path',
        default=MODEL_FILEPATH,
        help='Path to saved model weights. If this is set, we will use the ' \
              'provided weights as the starting point for training. If none, ' \
              'training will be done from scratch'
    )
    parser.add_argument(
        '--xy_train', default=TRAIN_FILEPATH,
        help='Path to xy dataframe that will be used for training. Should ' \
              'contain two columns, "FileName" and "SpeciesCode".'
    )
    parser.add_argument(
        '--xy_val', default=VAL_FILEPATH,
        help='Path to xy dataframe that will be used for validation. ' \
              'Should contain two columns, "FileName" and "SpeciesCode".'
    )
    parser.add_argument(
        '--xy_test', default=TEST_FILEPATH,
        help='Path to xy dataframe that will be used for testing. Should ' \
              'contain two columns, "FileName" and "SpeciesCode".'
    )
    parser.add_argument(
        '--skip_test', action='store_true',
        help='Set if testing should be skipped'
    )
    parser.add_argument(
        '--hyperparameters', default=HYPERPARAMETERS_FILEPATH,
        help='Path to save hyperparameters dataframe'
    )
    parser.add_argument(
        '--archi', default=ARCHI,
        help='Architecture of the model to be trained. Either inception, ' \
              'resnet50, resnet101, resnet152, wide_resnet50, or mobilenet'
    )
    parser.add_argument(
        '--no_pretraining', action='store_true',
        help='Set if you want the model to be trained from scratch'
    )
    parser.add_argument(
        '--train_only_classifier', action='store_true',
        help='Set if we train classification layer only'
    )
    parser.add_argument(
        '--num_workers', default=8, type=int,
        help='Number of threads to be set for the GPU'
    )
    parser.add_argument(
        '--use_cpu', action='store_true',
        help='Using CPU for processing'
    )
    parser.add_argument(
        '--num_classes', default=NUM_CLASSES, type=int,
        action='store', help='Number of classes to be trained'
    )
    parser.add_argument(
        '--dropout', default=DROPOUT, type=float,
        action='store', help='Dropout probablity'
    )
    parser.add_argument(
        '--lr', default=LEARNING_RATE, type=float, help='The learning rate'
    )
    parser.add_argument(
        '--betadist_alpha', default=BETADIST_ALPHA, type=float,
        help='The alpha value controlling the shape of the beta distribution ' \
              'for the Adam optimiser'
    )
    parser.add_argument(
        '--betadist_beta', default=BETADIST_BETA, type=float,
        help='The beta value controlling the shape of the beta distribution ' \
              'for the Adam optimiser'
    )
    parser.add_argument(
        '--eps', default=ADAM_EPS, type=float,
        help='Epsilon value for Adam optimiser'
    )
    parser.add_argument(
        '--weight_decay', default=WEIGHT_DECAY, type=float,
        help='Weight decay for Adam optimiser'
    )
    parser.add_argument(
        '--epochs', default=EPOCHS, type=int,
        help='Number of epochs to be run for training'
    )
    parser.add_argument(
        '--step_size', default=STEP_SIZE, type=int,
        help='Step size'
    )
    parser.add_argument(
        '--gamma', default=GAMMA, type=float,
        help='Gamma value for optimiser'
    )
    parser.add_argument(
        '--batch_size', default=BATCH_SIZE, type=int,
        help='Batch size for training'
    )
    parser.add_argument(
        '--img_resize', action='store_true',
        help='Resize each image before training/testing'
    )
    parser.add_argument(
        '--img_size', default=IMAGE_SIZE, type=int,
        help='Image size for each image, if img_resize is True'
    )
    parser.add_argument(
        '--crop_size', default='299', type=int,
        help='Crop size for each image. Inception v3 expects 299'
    )

    return parser


if __name__ == '__main__':
    parser = get_arg_parser()
    args = parser.parse_args()

    # Check that paths to save results exist and is empty
    if os.path.exists(args.results_path) \
       and len(os.listdir(args.results_path)) == 0:
        print("\nSaving results in " + args.results_path)
    else:
        sys.exit(
            "\nError: File path to save results do not exist, " \
            "or directory is not empty"
        )

    # Read data
    xy_train = pd.read_csv(args.xy_train)
    xy_val = pd.read_csv(args.xy_val)

    # Extract hyperparameters if further training from a pre-trained model
    if args.model_path is not None:
        hp_path = os.path.join(os.path.dirname(args.model_path),
                               'hyperparameter_records.csv')
        hp = pd.read_csv(hp_path)
        args.archi = hp.loc[
            hp['Hyperparameters'] == 'Architecture', 'Values'].item()
        args.weight_decay = float(hp.loc[
            hp['Hyperparameters'] == 'WeightDecay', 'Values'].item())
        args.dropout = float(hp.loc[
            hp['Hyperparameters'] == 'Dropout', 'Values'].item())
        args.num_classes = int(hp.loc[
            hp['Hyperparameters'] == 'NumClasses', 'Values'].item())
        args.train_only_classifier = eval(hp.loc[
            hp['Hyperparameters'] == 'TrainOnlyClassifier', 'Values'].item())
        args.img_size = int(hp.loc[
            hp['Hyperparameters'] == 'ImgSize', 'Values'].item())
        args.crop_size = int(hp.loc[
            hp['Hyperparameters'] == 'CropSize', 'Values'].item())

    # Check the image size for the first image
    if not args.img_resize:
        check_img_size(xy_train.FileName[0], "training set", args.img_size)
        check_img_size(xy_val.FileName[0], "validation set", args.img_size)

    train_dl = get_dataloader(
        xy_train.FileName, xy_train.SpeciesCode, args.batch_size,
        args.image_dir, args.crop_size, True, args.num_workers,
        args.img_resize, args.img_size
    )
    val_dl = get_dataloader(
        xy_val.FileName, xy_val.SpeciesCode, args.batch_size, args.image_dir,
        args.crop_size, False, args.num_workers, args.img_resize, args.img_size
    )

    print("\nDataset to be used includes {} training and {} validation images.".format(
        len(xy_train.FileName), len(xy_val.FileName)))

    if not args.skip_test:
        xy_test = pd.read_csv(args.xy_test)

        if not args.img_resize:
            check_img_size(xy_test.FileName[0], "testing set", args.img_size)
        
        test_dl = get_dataloader(
            xy_test.FileName, xy_test.SpeciesCode, args.batch_size, args.image_dir,
            args.crop_size, False, args.num_workers, args.img_resize, args.img_size
        )

        print("\nTesting will be conducted with {} testing images.".format(
            len(xy_test.FileName)))
    else:
        print('Testing will NOT be conducted\n')

    # Output hyperparameters for recording purposes
    hp_names = (
        "SkipTest", "NumWorkers", "ModelPath", "LearningRate",
        "BetaDist_alpha", "BetaDist_beta", "Eps", "WeightDecay",
        "Epochs", "StepSize", "Gamma", "BatchSize", "ImgSize",
        "CropSize", "Architecture", "NumClasses", "TrainOnlyClassifier",
        "Dropout", "NoPretraining", "NumTrainImages", "NumValImages"
    )
    hp_values = (
        args.skip_test, args.num_workers, args.model_path, args.lr,
        args.betadist_alpha, args.betadist_beta, args.eps, args.weight_decay,
        args.epochs, args.step_size, args.gamma, args.batch_size,
        args.img_size, args.crop_size, args.archi, args.num_classes,
        args.train_only_classifier, args.dropout, args.no_pretraining,
        len(xy_train.FileName), len(xy_val.FileName)
    )

    hp_records = pd.DataFrame(
        {'Hyperparameters': hp_names, 'Values': hp_values})
    hp_records.to_csv(index=False, path_or_buf=args.hyperparameters)
    print(hp_records.to_string())

    # Build model
    model, parameters = get_model(
        args.archi, args.num_classes, not args.train_only_classifier,
        not args.no_pretraining, args.dropout
    )

    # Prepare for training
    if not args.use_cpu:
        model.cuda()
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')

    if torch.backends.cudnn.is_available():
        print(
            "\nUsing {} with cuDNN version {} for training with {} architecture."
            .format(device, torch.backends.cudnn.version(), args.archi)
        )
    else:
        print(
            "\nUsing {} WITHOUT cuDNN for training with {} architecture."
            .format(device, args.archi)
        )

    betas = (args.betadist_alpha, args.betadist_beta)
    optimizer = optim.Adam(
        parameters,
        lr=args.lr,
        betas=betas,
        eps=args.eps,
        weight_decay=args.weight_decay,
    )
    loss_func = nn.CrossEntropyLoss()
    scheduler = optim.lr_scheduler.StepLR(
        optimizer,
        step_size=args.step_size,
        gamma=args.gamma
    )
    if args.model_path is not None:
        load_checkpoint(args.model_path, model, optimizer, scheduler)

    # Train and validate
    (weights, train_loss, train_acc, val_loss, val_acc,
        train_val_results) = train_validate(
        args.epochs, model, optimizer, scheduler, loss_func,
        train_dl, val_dl, device, args.archi,
        args.results_path
    )

    train_val_results.to_csv(
        index=False,
        path_or_buf=os.path.join(
            args.results_path, 'train_val_results.csv')
    )

    # Test
    if args.skip_test:
        print("\nTesting will not be conducted. Exiting now.")
        sys.exit()

    print("Training and validation complete. Starting testing now.")
    model.load_state_dict(weights)
    test_acc, test_loss, probabilities = evaluate_model(
        model, test_dl, loss_func, device)
    print("Test acc: {}, Test loss: {}".format(test_acc, test_loss))

    # Saving test results, probabilities and metadata
    save_test_results(
        test_acc, test_loss, probabilities, args.num_classes, xy_test.FileName,
        args.results_path, args.model_path, args.xy_test,
        args.hyperparameters)

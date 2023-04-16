import os
import cv2
from SegTracker import SegTracker
from model_args import segtracker_args,sam_args,aot_args
from PIL import Image
from aot_tracker import _palette
import numpy as np
import torch
import gc
import imageio

def save_prediction(pred_mask,output_dir,file_name):
    save_mask = Image.fromarray(pred_mask.astype(np.uint8))
    save_mask = save_mask.convert(mode='P')
    save_mask.putpalette(_palette)
    save_mask.save(os.path.join(output_dir,file_name))
def colorize_mask(pred_mask):
    save_mask = Image.fromarray(pred_mask.astype(np.uint8))
    save_mask = save_mask.convert(mode='P')
    save_mask.putpalette(_palette)
    save_mask = save_mask.convert(mode='RGB')
    return np.array(save_mask)

aot_model2ckpt = {
    "deaotb": "./ckpt/DeAOTB_PRE_YTB_DAV.pth",
    "deaotl": "./ckpt/DeAOTL_PRE_YTB_DAV",
    "r50_deaotl": "./ckpt/R50_DeAOTL_PRE_YTB_DAV.pth",
}


def seg_track_anything(input_video_file, aot_model, sam_gap, max_obj_num, points_per_side):
    video_name = os.path.basename(input_video_file).split('.')[0]
    io_args = {
        'input_video': f'{input_video_file}',
        'output_mask_dir': f'./assets/{video_name}_masks',
        'save_video': True,
        'output_video': f'./assets/{video_name}_seg.mp4', # keep same format as input video
        'output_gif': f'./assets/{video_name}_seg.gif',
    }

    # reset aot args
    aot_args["model"] = aot_model
    aot_args["model_path"] = aot_model2ckpt[aot_model]
    # reset sam args
    sam_args["sam_gap"] = sam_gap
    sam_args["max_obj_num"] = max_obj_num
    sam_args["points_per_side"] = points_per_side

    output_dir = io_args['output_mask_dir']
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    # source video to segment
    cap = cv2.VideoCapture(io_args['input_video'])
    fps = cap.get(cv2.CAP_PROP_FPS)
    # output masks
    output_dir = io_args['output_mask_dir']
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if io_args['save_video']:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        num_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        out = cv2.VideoWriter(io_args['output_video'], fourcc, fps, (width, height))
    pred_list = []

    torch.cuda.empty_cache()
    gc.collect()
    sam_gap = segtracker_args['sam_gap']
    frame_idx = 0
    segtracker = SegTracker(segtracker_args,sam_args,aot_args)
    segtracker.restart_tracker()


    with torch.cuda.amp.autocast():
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_idx == 0:
                pred_mask = segtracker.seg(frame)
                torch.cuda.empty_cache()
                gc.collect()
                segtracker.add_reference(frame, pred_mask, frame_idx)
            elif (frame_idx % sam_gap) == 0:
                seg_mask = segtracker.seg(frame)
                torch.cuda.empty_cache()
                gc.collect()
                track_mask = segtracker.track(frame)
                # find new objects, and update tracker with new objects
                new_obj_mask = segtracker.find_new_objs(track_mask,seg_mask)
                save_prediction(new_obj_mask,output_dir,str(frame_idx)+'_new.png')
                pred_mask = track_mask + new_obj_mask
                # segtracker.restart_tracker()
                segtracker.add_reference(frame, pred_mask, frame_idx)
            else:
                pred_mask = segtracker.track(frame,update_memory=True)
            torch.cuda.empty_cache()
            gc.collect()
            
            save_prediction(pred_mask,output_dir,str(frame_idx)+'.png')
            masked_frame = (frame*0.3+colorize_mask(pred_mask)*0.7).astype(np.uint8)
            pred_list.append(masked_frame)
            if io_args['save_video']:
                out.write(masked_frame)
            
            print("processed and saved mask for frame {}, obj_num {}".format(frame_idx,segtracker.get_obj_num()),end='\r')
            frame_idx += 1
    cap.release()
    if io_args['save_video']:
        out.release()
        print("\n{} saved".format(io_args['output_video']))
    # save a gif
    imageio.mimsave(io_args['output_gif'],pred_list,fps=fps)
    print("{} saved".format(io_args['output_gif']))
    print('\nfinished')
    
    # zip predicted mask
    os.system(f"zip -r ./assets/{video_name}_pred_mask.zip {io_args['output_mask_dir']}")
    
    return io_args["output_video"], f"./assets/{video_name}_pred_mask.zip"
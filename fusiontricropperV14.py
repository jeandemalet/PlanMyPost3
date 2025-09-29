# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk, ImageOps, ImageEnhance, ImageFont
import os
import shutil
import traceback
import sys
import re
import urllib.parse
import json
import time # Importé pour les dates EXIF et de modification
import datetime # Pour le calendrier
import calendar # Pour le calendrier
import glob # Pour trouver les images dans les dossiers "jour"

# --- Constantes Globales ---
JOUR_COLORS = [ # Renamed from COULOIR_COLORS
    "red", "blue", "green", "purple", "orange",
    "brown", "magenta", "gold", "cyan", "darkgreen",
    "pink", "navy", "gray", "darkorange"
]
FILENAME_DELIMITER = "__"
CROP_CACHE_SUBDIR = ".crop_cache"
SCHEDULE_FILENAME = "schedule_data.json" # Nom du fichier de programmation

THUMBNAIL_RESAMPLING_FILTER = Image.Resampling.BILINEAR
CROPPER_RESIZE_FILTER = Image.Resampling.BILINEAR
CALENDAR_THUMB_SIZE = (40, 40) # For small preview in calendar cell
CALENDAR_HOVER_THUMB_SIZE = (150, 150) # For enlarged hover preview
MAX_HOVER_PREVIEWS = 5 # Max images to show in hover preview

# --- Helper Functions for Filename Encoding (PublicationOrganizer) ---
def safe_encode_basename(basename):
    encoded = basename.replace(FILENAME_DELIMITER, "_DPLDLM_")
    return urllib.parse.quote(encoded, safe='')

def safe_decode_basename(encoded_basename):
    decoded = urllib.parse.unquote(encoded_basename)
    return decoded.replace("_DPLDLM_", FILENAME_DELIMITER)

# --- GridItem (PublicationOrganizer) ---
class GridItem(tk.Canvas):
    def __init__(self, parent, file_path, initial_thumb_size=(100, 100), margin=10):
        self.parent_frame = parent
        self.file_path = file_path
        self.thumb_size = initial_thumb_size
        self.margin = margin
        self._pil_original = None
        self._pil_thumb = None
        self.normal_photo = None
        self.dim_photo = None
        self.is_valid = True

        # Métadonnées pour le tri
        self.basename = os.path.basename(file_path)
        self.datetime_original_ts = None # Timestamp (float)
        try:
            self.file_mod_time_ts = os.path.getmtime(file_path)
        except OSError:
             self.file_mod_time_ts = 0.0

        canvas_w = self.thumb_size[0] + 2 * self.margin
        canvas_h = self.thumb_size[1] + 2 * self.margin
        super().__init__(parent, width=canvas_w, height=canvas_h, bg="white",
                         highlightthickness=1, relief="ridge")
        try:
            self._pil_original = Image.open(file_path)
            self._pil_original = ImageOps.exif_transpose(self._pil_original)

            try:
                exif_data = self._pil_original.getexif()
                if exif_data:
                    datetime_str = exif_data.get(36867) or exif_data.get(306)
                    if datetime_str and isinstance(datetime_str, str):
                        try:
                            if ':' in datetime_str and ' ' in datetime_str:
                                self.datetime_original_ts = time.mktime(time.strptime(datetime_str, '%Y:%m:%d %H:%M:%S'))
                            elif '-' in datetime_str and ' ' in datetime_str:
                                 self.datetime_original_ts = time.mktime(time.strptime(datetime_str, '%Y-%m-%d %H:%M:%S'))
                        except (ValueError, TypeError):
                            pass
                    elif datetime_str and isinstance(datetime_str, tuple) and datetime_str:
                         try:
                             self.datetime_original_ts = time.mktime(time.strptime(datetime_str[0], '%Y:%m:%d %H:%M:%S'))
                         except (ValueError, TypeError, IndexError):
                             pass
            except Exception:
                pass

            if self._pil_original.mode not in ['RGB', 'RGBA', 'LA']:
                 self._pil_original = self._pil_original.convert('RGB')
            elif self._pil_original.mode == 'P' and 'transparency' in self._pil_original.info:
                 self._pil_original = self._pil_original.convert('RGBA')

        except Exception as e:
            print(f"ERREUR chargement image originale {os.path.basename(file_path)}: {e}")
            self.is_valid = False
            self._pil_original = None
            placeholder_pil_content = Image.new('RGB', (self.thumb_size[0]//2, self.thumb_size[1]//2), color='gray')
            final_placeholder = Image.new('RGB', self.thumb_size, color='lightgrey')
            px = (self.thumb_size[0] - placeholder_pil_content.width) // 2
            py = (self.thumb_size[1] - placeholder_pil_content.height) // 2
            final_placeholder.paste(placeholder_pil_content, (px,py))
            self.normal_photo = ImageTk.PhotoImage(final_placeholder)
            self.dim_photo = self.normal_photo
            cx, cy = canvas_w // 2, canvas_h // 2
            self.create_text(cx, cy, text=f"ERREUR\nChargement\n{os.path.basename(file_path)}",
                             fill="red", font=("Arial", 8, "bold"), justify="center", tags="err_text")
        if self.is_valid:
            self._create_photo_images()

        self.used = False
        self.order = None
        self.color = "red"
        cx = canvas_w // 2
        cy = canvas_h // 2
        if self.normal_photo:
             self.image_id = self.create_image(cx, cy, anchor="center", image=self.normal_photo, tags="img")
        else:
             self.image_id = None
        self.text_id = self.create_text(cx, cy, text="", font=("Helvetica", 20, "bold"),
                                        fill=self.color, state='hidden', tags="order_text")
        self.tag_raise(self.text_id)
        self.click_callback = None
        self.bind("<Button-1>", self.on_click)

    def _create_photo_images(self):
        if not self._pil_original or not self.is_valid:
             if not self.normal_photo:
                 placeholder_pil_content = Image.new('RGB', (self.thumb_size[0]//2, self.thumb_size[1]//2), color='gray')
                 final_placeholder = Image.new('RGB', self.thumb_size, color='lightgrey')
                 px = (self.thumb_size[0] - placeholder_pil_content.width) // 2
                 py = (self.thumb_size[1] - placeholder_pil_content.height) // 2
                 final_placeholder.paste(placeholder_pil_content, (px,py))
                 self.normal_photo = ImageTk.PhotoImage(final_placeholder)
                 self.dim_photo = self.normal_photo
             self._pil_thumb = None
             if not self.find_withtag("err_text"):
                 w = self.winfo_reqwidth(); h = self.winfo_reqheight()
                 self.create_text(w // 2, h // 2, text="ERREUR", fill="red", font=("Arial", 9, "bold"), justify="center", tags="err_text")
             return
        try:
            img_copy_for_thumb = self._pil_original.copy()
            img_copy_for_thumb.thumbnail(self.thumb_size, THUMBNAIL_RESAMPLING_FILTER)
            self._pil_thumb = img_copy_for_thumb

            final_thumb_pil = Image.new('RGB', self.thumb_size, (255, 255, 255))
            paste_x = (self.thumb_size[0] - self._pil_thumb.width) // 2
            paste_y = (self.thumb_size[1] - self._pil_thumb.height) // 2
            image_to_paste_on_final_thumb = self._pil_thumb
            mask_for_paste = None

            if self._pil_thumb.mode == 'RGBA':
                mask_for_paste = self._pil_thumb.split()[3]
            elif self._pil_thumb.mode == 'LA':
                image_to_paste_on_final_thumb = self._pil_thumb.convert('RGBA')
                mask_for_paste = image_to_paste_on_final_thumb.split()[3]
            elif self._pil_thumb.mode == 'P' and 'transparency' in self._pil_thumb.info:
                image_to_paste_on_final_thumb = self._pil_thumb.convert('RGBA')
                mask_for_paste = image_to_paste_on_final_thumb.split()[3]
            elif self._pil_thumb.mode != 'RGB':
                image_to_paste_on_final_thumb = self._pil_thumb.convert('RGB')

            final_thumb_pil.paste(image_to_paste_on_final_thumb, (paste_x, paste_y), mask=mask_for_paste)
            self.normal_photo = ImageTk.PhotoImage(final_thumb_pil)
            enhancer = ImageEnhance.Brightness(final_thumb_pil)
            dimmed_pil_rgb = enhancer.enhance(0.6)
            self.dim_photo = ImageTk.PhotoImage(dimmed_pil_rgb)

        except Exception as e:
            print(f"ERREUR generation PhotoImage pour {os.path.basename(self.file_path)} (taille {self.thumb_size}): {e}")
            placeholder_pil_content = Image.new('RGB', (self.thumb_size[0]//2, self.thumb_size[1]//2), color='darkred')
            final_placeholder = Image.new('RGB', self.thumb_size, color='lightgrey')
            px = (self.thumb_size[0] - placeholder_pil_content.width) // 2
            py = (self.thumb_size[1] - placeholder_pil_content.height) // 2
            final_placeholder.paste(placeholder_pil_content, (px,py))
            self.normal_photo = ImageTk.PhotoImage(final_placeholder)
            self.dim_photo = self.normal_photo
            self._pil_thumb = None
            if not self.find_withtag("err_text"):
                 w = self.winfo_reqwidth(); h = self.winfo_reqheight()
                 self.create_text(w // 2, h // 2, text="ERREUR\nGénér.", fill="red", font=("Arial", 9, "bold"), justify="center", tags="err_text")

    def update_size(self, new_thumb_size):
        if not self.is_valid or new_thumb_size == self.thumb_size:
             return
        self.thumb_size = new_thumb_size
        self._create_photo_images()

        new_canvas_w = self.thumb_size[0] + 2 * self.margin
        new_canvas_h = self.thumb_size[1] + 2 * self.margin
        self.config(width=new_canvas_w, height=new_canvas_h)

        cx = new_canvas_w // 2; cy = new_canvas_h // 2

        if self.image_id:
             current_image_to_display = self.dim_photo if self.used else self.normal_photo
             if current_image_to_display:
                 try:
                     self.itemconfig(self.image_id, image=current_image_to_display)
                     self.coords(self.image_id, cx, cy)
                 except tk.TclError:
                     self.image_id = None
             else:
                self.image_id = None

        if self.image_id is None and self.normal_photo:
             self.image_id = self.create_image(cx, cy, anchor="center", image=self.normal_photo, tags="img")
             if self.used: self.itemconfig(self.image_id, image=self.dim_photo)

        if self.text_id:
            try:
                self.coords(self.text_id, cx, cy)
                if self.used: self._update_order_text_appearance()
                self.tag_raise(self.text_id)
            except tk.TclError:
                self.text_id = None

        err_text_items = self.find_withtag("err_text")
        if err_text_items:
            for item_id in err_text_items:
                 try:
                     self.coords(item_id, cx, cy); self.tag_raise(item_id)
                 except tk.TclError:
                     pass

    def _update_order_text_appearance(self):
        if not self.text_id or not self.is_valid: return
        try:
            if self.used and self.order is not None:
                font_size = max(10, min(24, int(self.thumb_size[1] * 0.25)))
                font = ("Helvetica", font_size, "bold")
                self.itemconfig(self.text_id, text=str(self.order), fill=self.color, state='normal', font=font)
                self.tag_raise(self.text_id)
            else:
                self.itemconfig(self.text_id, text="", state='hidden')
        except tk.TclError:
            self.text_id = None

    def on_click(self, event):
        try:
             organizer = self.parent_frame.master.master.master.master.master
             if hasattr(organizer, 'is_external_dragging') and organizer.is_external_dragging():
                 return "break"
        except AttributeError:
            pass
        if self.click_callback:
            self.click_callback(self)

    def mark_used(self, order, color="red"):
        if not self.is_valid: return
        if not self.used or self.order != order or self.color != color:
            self.used = True; self.order = order; self.color = color
            if self.dim_photo and self.image_id:
                try:
                    self.itemconfig(self.image_id, image=self.dim_photo)
                except tk.TclError:
                    self.image_id = None
            self._update_order_text_appearance()

    def mark_unused(self):
        if not self.is_valid: return
        if self.used:
            self.used = False; self.order = None
            if self.normal_photo and self.image_id:
                try:
                    self.itemconfig(self.image_id, image=self.normal_photo)
                except tk.TclError:
                    self.image_id = None
            self._update_order_text_appearance()

# --- JourFrame (formerly Corridor) ---
class JourFrame: # Renamed from Corridor
    def __init__(self, parent_frame, organizer, index, base_dir, update_callback=None, max_images=20):
        self.organizer = organizer
        self.index = index
        self.letter = chr(ord('A') + index)
        self.base_dir = base_dir
        self.update_callback = update_callback
        self.max_images = max_images

        try:
            default_bg = parent_frame.cget('bg')
        except tk.TclError:
            default_bg = "SystemButtonFace" if sys.platform == "win32" else "#D9D9D9"

        self.frame = tk.Frame(parent_frame, bd=2, relief="groove", bg=default_bg)
        button_frame = tk.Frame(self.frame, bg=default_bg)
        button_frame.pack(side=tk.RIGHT, padx=5, pady=5, fill=tk.Y)
        self.save_btn = tk.Button(button_frame, text="💾 Enregistrer", command=self.save)
        self.save_btn.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.save_btn_original_bg = self.save_btn.cget("background")
        self.crop_btn = tk.Button(button_frame, text="✂️ Recadrer", command=self.open_cropper_for_jour) # Renamed
        self.crop_btn.pack(side=tk.TOP, fill=tk.X, pady=(2, 2))
        self.close_btn = tk.Button(button_frame, text="❌ Fermer", command=self.close_jour) # Renamed
        self.close_btn.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))
        self.label = tk.Label(self.frame, text=f"Jour {self.letter}", font=("Helvetica", 14, "bold"), bg="lightgray") # Renamed "Couloir" to "Jour"
        self.label.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        self.canvas_height = 120
        self.canvas = tk.Canvas(self.frame, height=self.canvas_height, bg="white")
        self.canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.images_data = []
        self.photos = []
        self.items = []
        self.del_btn_ids = []

        self.thumb_size = (100, 100)
        self.margin = 10
        self.dragging_item = None; self.dragging_index = None; self.drag_offset_x = 0
        self.frame.bind("<Button-1>", self._on_frame_click)
        self.label.bind("<Button-1>", self._on_frame_click)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self._on_jour_canvas_mousewheel) # Renamed
        self.canvas.bind("<Button-4>", self._on_jour_canvas_mousewheel)
        self.canvas.bind("<Button-5>", self._on_jour_canvas_mousewheel)

    def open_cropper_for_jour(self): # Renamed
        if not self.images_data:
            messagebox.showinfo("Recadrage", f"Le Jour {self.letter} est vide. Ajoutez des images avant de recadrer.", parent=self.frame)
            return

        current_display_paths_passed_to_cropper = [data[0] for data in self.images_data]
        organizer_cache_dir = os.path.join(self.organizer.base_dir, CROP_CACHE_SUBDIR)
        os.makedirs(organizer_cache_dir, exist_ok=True)

        cropper_instance = ImageCropperPopup(
            parent=self.organizer.root,
            image_paths_to_load=current_display_paths_passed_to_cropper,
            target_base_save_dir=organizer_cache_dir
        )
        self.organizer.root.wait_window(cropper_instance)

        if hasattr(cropper_instance, 'modified_paths_map') and cropper_instance.modified_paths_map:
            changes_applied_to_jour = False # Renamed
            new_image_data_list_for_jour = [] # Renamed

            for idx in range(len(self.images_data)):
                path_in_jour_before_crop, original_ref_path_of_item = self.images_data[idx] # Renamed
                modification_output = cropper_instance.modified_paths_map.get(path_in_jour_before_crop)

                if modification_output:
                    changes_applied_to_jour = True # Renamed
                    if isinstance(modification_output, list):
                        for new_split_img_path_str in modification_output:
                            new_image_data_list_for_jour.append( (new_split_img_path_str, original_ref_path_of_item) )
                    elif isinstance(modification_output, str):
                        new_image_data_list_for_jour.append( (modification_output, original_ref_path_of_item) )
                    else:
                        new_image_data_list_for_jour.append( (path_in_jour_before_crop, original_ref_path_of_item) )
                else:
                    new_image_data_list_for_jour.append( (path_in_jour_before_crop, original_ref_path_of_item) )

            if changes_applied_to_jour: # Renamed
                self.images_data = new_image_data_list_for_jour
                self.rebuild_and_reposition()
                self._reset_save_button_color(mark_unsaved=True)
                if self.update_callback: self.update_callback()

    def _on_jour_canvas_mousewheel(self, event): # Renamed
        if self.organizer:
            self.organizer._on_jour_frames_area_mousewheel(event) # Renamed from _on_corridor_mousewheel
            return "break"

    def _on_frame_click(self, event):
        if self.organizer and self.organizer.is_external_dragging():
             return "break"
        if event.widget == self.frame or event.widget == self.label:
            if self.organizer: self.organizer.set_current_jour_frame(self) # Renamed
        return "break"

    def _calculate_insert_index(self, canvas_x):
        target_index = 0
        item_slot_width = self.thumb_size[0] + self.margin
        relative_x = canvas_x - (self.margin / 2)
        if relative_x > 0 and item_slot_width > 0:
             slot_index = int((relative_x / item_slot_width) + 0.5)
             target_index = max(0, min(slot_index, len(self.items)))
        else:
             target_index = 0
        return target_index

    def add_image(self, file_path_tuple):
        return self.insert_image_at(file_path_tuple, len(self.images_data))

    def insert_image_at(self, file_path_tuple, index):
        display_path, original_reference_path = file_path_tuple

        if len(self.images_data) >= self.max_images:
            msg = f"[Jour {self.letter}] Limite de {self.max_images} images atteinte." # Renamed
            if not (self.organizer and self.organizer._initializing):
                 messagebox.showwarning("Limite Atteinte", msg, parent=self.frame)
            return False

        norm_display_path = os.path.normcase(display_path)
        if any(os.path.normcase(data[0]) == norm_display_path for data in self.images_data):
            return False

        try:
            img = Image.open(display_path)
            img = ImageOps.exif_transpose(img)
            img.thumbnail(self.thumb_size, THUMBNAIL_RESAMPLING_FILTER)

            if img.mode == 'RGBA' or img.mode == 'LA' or (img.mode == 'P' and 'transparency' in img.info):
                 bg = Image.new('RGB', img.size, (255, 255, 255))
                 img_to_paste = img
                 if img.mode == 'LA': img_to_paste = img.convert('RGBA')
                 elif img.mode == 'P': img_to_paste = img.convert('RGBA')
                 bg.paste(img_to_paste, mask=img_to_paste.split()[-1])
                 photo = ImageTk.PhotoImage(bg)
            else:
                 photo = ImageTk.PhotoImage(img.convert('RGB'))
        except Exception as e:
            error_message = f"ERREUR chargement image {os.path.basename(display_path)} pour Jour {self.letter}: {e}" # Renamed
            print(error_message)
            if not (self.organizer and self.organizer._initializing):
                messagebox.showerror("Erreur Image", f"Impossible de charger l'image pour le Jour {self.letter}:\n{os.path.basename(display_path)}\n\n{e}", parent=self.frame)
            return False

        index = max(0, min(index, len(self.images_data)))
        self.images_data.insert(index, file_path_tuple)
        self.photos.insert(index, photo)

        y_center_img = self.canvas_height // 2
        initial_x = self.margin + index * (self.thumb_size[0] + self.margin) + (self.thumb_size[0] // 2)

        item_id = self.canvas.create_image(initial_x, y_center_img, anchor="center", image=photo, tags=f"img_{index}")
        self.items.insert(index, item_id)

        del_btn_widget = self._create_delete_btn(item_id)
        btn_x = initial_x + self.thumb_size[0] // 2 - 2
        btn_y = y_center_img - self.thumb_size[1] // 2 + 2
        btn_id = self.canvas.create_window(btn_x, btn_y, window=del_btn_widget, anchor="ne", tags=f"btn_{index}")
        self.del_btn_ids.insert(index, btn_id)

        self._reset_save_button_color(mark_unsaved=True)
        self.reposition_all()
        if self.update_callback: self.update_callback()
        return True

    def _create_delete_btn(self, item_id_to_delete):
        size = 20
        btn_canvas = tk.Canvas(self.canvas, width=size, height=size, bd=0, highlightthickness=0, bg="white", cursor="hand2")
        btn_canvas.create_oval(1, 1, size-1, size-1, fill="white", outline="gray", tags="bg")
        btn_canvas.create_text(size//2, size//2 -1 , text="✕", fill="black", font=('Arial', 10, 'bold'), tags="fg")
        btn_canvas.bind("<Button-1>", lambda event, img_id=item_id_to_delete: self.canvas.after(1, self.remove_item_by_id, img_id))
        btn_canvas.bind("<Enter>", lambda e: btn_canvas.itemconfig("bg", fill="lightcoral"))
        btn_canvas.bind("<Leave>", lambda e: btn_canvas.itemconfig("bg", fill="white"))
        return btn_canvas

    def _remove_item_at_index(self, idx_to_remove):
        if not (0 <= idx_to_remove < len(self.items) and
                0 <= idx_to_remove < len(self.images_data) and
                0 <= idx_to_remove < len(self.photos) and
                0 <= idx_to_remove < len(self.del_btn_ids)):
            print(f"Jour {self.letter}: Inconsistent index {idx_to_remove} for removal. Forcing rebuild.") # Renamed
            self.rebuild_and_reposition()
            return False

        item_id_on_canvas = self.items[idx_to_remove]
        del_btn_window_id_on_canvas = self.del_btn_ids[idx_to_remove]

        try:
            del self.images_data[idx_to_remove]
            del self.photos[idx_to_remove]
            del self.items[idx_to_remove]
            del self.del_btn_ids[idx_to_remove]
        except IndexError:
            print(f"Jour {self.letter}: IndexError during data deletion at index {idx_to_remove}. Forcing rebuild.") # Renamed
            self.rebuild_and_reposition()
            return False

        canvas_cleanup_failed = False
        try:
            if self.canvas and self.canvas.winfo_exists():
                if del_btn_window_id_on_canvas in self.canvas.find_all():
                    if self.canvas.type(del_btn_window_id_on_canvas) == 'window':
                        widget_path = self.canvas.itemcget(del_btn_window_id_on_canvas, "-window")
                        if widget_path:
                            widget = self.canvas.nametowidget(widget_path)
                            if widget and widget.winfo_exists():
                                widget.destroy()
                    self.canvas.delete(del_btn_window_id_on_canvas)

                if item_id_on_canvas in self.canvas.find_all():
                    self.canvas.delete(item_id_on_canvas)
        except tk.TclError as e_tcl:
            print(f"Jour {self.letter}: TclError during canvas cleanup for item at old index {idx_to_remove}: {e_tcl}.") # Renamed
            canvas_cleanup_failed = True
        except Exception as e_gen:
            print(f"Jour {self.letter}: Exception during canvas cleanup for item at old index {idx_to_remove}. Error: {e_gen}.") # Renamed
            canvas_cleanup_failed = True

        if canvas_cleanup_failed:
            print(f"Jour {self.letter}: Canvas cleanup failed for index {idx_to_remove}. Forcing rebuild.") # Renamed
            self.rebuild_and_reposition()
            return False

        self._reset_save_button_color(mark_unsaved=True)
        self.reposition_all()
        if self.update_callback:
            self.update_callback()
        return True


    def remove_item_by_id(self, item_id_from_canvas):
        if not self.canvas or not self.canvas.winfo_exists():
            return False
        try:
            idx = self.items.index(item_id_from_canvas)
            return self._remove_item_at_index(idx)
        except ValueError:
            print(f"Jour {self.letter}: item_id {item_id_from_canvas} not found in self.items for removal by ID. Forcing rebuild.") # Renamed
            self.rebuild_and_reposition()
            return False

    def remove_image_by_display_path(self, display_path_to_remove):
        if not self.canvas or not self.canvas.winfo_exists(): return True

        norm_path_to_remove = os.path.normcase(display_path_to_remove)
        found_index = -1
        for i, (dp, _) in enumerate(self.images_data):
            if os.path.normcase(dp) == norm_path_to_remove:
                found_index = i
                break

        if found_index == -1:
            return True

        return self._remove_item_at_index(found_index)


    def remove_image_by_original_reference_path(self, original_reference_path_to_remove):
        if not self.canvas or not self.canvas.winfo_exists(): return False

        norm_orig_ref_to_remove = os.path.normcase(original_reference_path_to_remove)
        indices_to_remove = []
        for i, (dp, orp) in enumerate(self.images_data):
            if os.path.normcase(orp) == norm_orig_ref_to_remove:
                indices_to_remove.append(i)

        if not indices_to_remove:
            return False

        all_removed_successfully = True
        for idx in sorted(indices_to_remove, reverse=True):
            if not self._remove_item_at_index(idx):
                all_removed_successfully = False
        return all_removed_successfully


    def rebuild_and_reposition(self):
         if not self.canvas or not self.canvas.winfo_exists(): return
         # print(f"[Jour {self.letter}] Rebuilding and Repositioning. Current items in images_data: {len(self.images_data)}") # Renamed

         valid_image_data_tuples = list(self.images_data)

         try:
             window_item_ids = self.canvas.find_withtag('window')
             if window_item_ids:
                 for win_id in window_item_ids:
                      try:
                          widget_path = self.canvas.itemcget(win_id, "-window")
                          if widget_path:
                              widget = self.canvas.nametowidget(widget_path)
                              if widget and widget.winfo_exists(): widget.destroy()
                      except Exception: pass
             self.canvas.delete("all")
         except Exception as e: print(f"  WARNING: Error clearing canvas during rebuild: {e}")

         self.photos.clear(); self.items.clear(); self.del_btn_ids.clear(); self.images_data.clear()

         y_center_img = self.canvas_height // 2
         current_x_center = self.margin + self.thumb_size[0] // 2

         for i, (display_p, original_ref_p) in enumerate(valid_image_data_tuples):
             try:
                 img = Image.open(display_p); img = ImageOps.exif_transpose(img)
                 img.thumbnail(self.thumb_size, THUMBNAIL_RESAMPLING_FILTER)
                 if img.mode == 'RGBA' or img.mode == 'LA' or (img.mode == 'P' and 'transparency' in img.info):
                     bg = Image.new('RGB', img.size, (255,255,255)); img_to_paste = img
                     if img.mode == 'LA': img_to_paste = img.convert('RGBA')
                     elif img.mode == 'P': img_to_paste = img.convert('RGBA')
                     bg.paste(img_to_paste, mask=img_to_paste.split()[-1]); photo = ImageTk.PhotoImage(bg)
                 else: photo = ImageTk.PhotoImage(img.convert('RGB'))

                 self.images_data.append((display_p, original_ref_p))
                 self.photos.append(photo)

                 x = current_x_center
                 item_id = self.canvas.create_image(x, y_center_img, anchor="center", image=photo, tags=f"img_{i}")
                 self.items.append(item_id)

                 del_btn_widget = self._create_delete_btn(item_id)
                 btn_x = x + self.thumb_size[0] // 2 - 2; btn_y = y_center_img - self.thumb_size[1] // 2 + 2
                 btn_id = self.canvas.create_window(btn_x, btn_y, window=del_btn_widget, anchor="ne", tags=f"btn_{i}")
                 self.del_btn_ids.append(btn_id)

                 current_x_center += self.thumb_size[0] + self.margin
             except Exception as e:
                 print(f"[Jour {self.letter}] ERROR during rebuild: Failed for '{os.path.basename(display_p)}': {e}") # Renamed
                 if (display_p, original_ref_p) in self.images_data:
                     try:
                         self.images_data.remove((display_p, original_ref_p))
                     except ValueError: pass

         if not (len(self.images_data) == len(self.photos) == len(self.items) == len(self.del_btn_ids)):
             print(f"[Jour {self.letter}] CRITICAL ERROR: Lists inconsistent *after* rebuild! Lengths: data={len(self.images_data)}, photos={len(self.photos)}, items={len(self.items)}, del_btns={len(self.del_btn_ids)}.") # Renamed

         self.update_scroll_region(); self._reset_save_button_color(mark_unsaved=True)
         if self.update_callback: self.update_callback()


    def reposition_all(self):
        if not self.canvas or not self.canvas.winfo_exists(): return

        if not (len(self.items) == len(self.del_btn_ids) == len(self.images_data) == len(self.photos)):
             print(f"Jour {self.letter}: Inconsistency detected in reposition_all. Forcing rebuild. Lengths: data={len(self.images_data)}, photos={len(self.photos)}, items={len(self.items)}, del_btns={len(self.del_btn_ids)}") # Renamed
             self.rebuild_and_reposition(); return

        y_center_img = self.canvas_height // 2
        current_x_center = self.margin + self.thumb_size[0] // 2

        for i, item_id_in_list in enumerate(self.items):
            del_btn_id_in_list = self.del_btn_ids[i]
            try:
                 try:
                     self.canvas.itemconfig(item_id_in_list)
                     self.canvas.itemconfig(del_btn_id_in_list)
                 except tk.TclError:
                     print(f"Jour {self.letter}: Item {item_id_in_list} or btn {del_btn_id_in_list} (index {i}) not on canvas during reposition. Forcing rebuild.") # Renamed
                     self.rebuild_and_reposition(); return

                 target_x_img = current_x_center; target_y_img = y_center_img
                 target_x_btn = target_x_img + self.thumb_size[0] // 2 - 2
                 target_y_btn = target_y_img - self.thumb_size[1] // 2 + 2

                 self.canvas.coords(item_id_in_list, target_x_img, target_y_img)
                 self.canvas.coords(del_btn_id_in_list, target_x_btn, target_y_btn)
                 self.canvas.tag_raise(item_id_in_list); self.canvas.tag_raise(del_btn_id_in_list)
                 current_x_center += self.thumb_size[0] + self.margin

            except tk.TclError as e:
                 print(f"Jour {self.letter}: TclError during reposition_all for item {item_id_in_list} (index {i}): {e}. Forcing rebuild.") # Renamed
                 self.rebuild_and_reposition(); return
            except IndexError:
                 print(f"Jour {self.letter}: IndexError during reposition_all. Forcing rebuild.") # Renamed
                 self.rebuild_and_reposition(); return

        self.update_scroll_region()


    def update_scroll_region(self):
        try:
             if not self.canvas or not self.canvas.winfo_exists(): return
             content_width_calculated = 0
             if self.items:
                 last_center_x = self.margin + self.thumb_size[0] // 2 + \
                                 (len(self.items) - 1) * (self.thumb_size[0] + self.margin)
                 content_width_calculated = last_center_x + self.thumb_size[0] // 2 + self.margin
             content_width_calculated = max(1, content_width_calculated)

             req_width = max(content_width_calculated, self.canvas.winfo_width(), 1)
             req_height = self.canvas_height
             self.canvas.config(scrollregion=(0, 0, req_width, req_height))
        except tk.TclError: pass
        except Exception as e: print(f"Warning: Error updating scroll region for Jour {self.letter}: {e}") # Renamed

    def on_press(self, event):
        if self.organizer and self.organizer.is_external_dragging(): return "break"
        if not self.canvas or not self.canvas.winfo_exists(): return

        try:
            canvas_x = self.canvas.canvasx(event.x);
            items_under_cursor = self.canvas.find_withtag("current")
            clicked_item_id = items_under_cursor[0] if items_under_cursor else None
        except tk.TclError: return
        except Exception: return

        clicked_delete_button = False
        if clicked_item_id:
            if self.canvas.type(clicked_item_id) == 'window' and clicked_item_id in self.del_btn_ids:
                clicked_delete_button = True
            widget_under_cursor = event.widget
            if isinstance(widget_under_cursor, tk.Canvas) and widget_under_cursor.master == self.canvas:
                 for btn_id in self.del_btn_ids:
                     if self.canvas.type(btn_id) == 'window':
                         win_path = self.canvas.itemcget(btn_id, "-window")
                         if win_path and self.canvas.nametowidget(win_path) == widget_under_cursor:
                             clicked_delete_button = True; break

        if clicked_delete_button:
            self.dragging_item = None; self.dragging_index = None; return

        if clicked_item_id and clicked_item_id in self.items:
            try:
                 self.dragging_item = clicked_item_id
                 self.dragging_index = self.items.index(clicked_item_id)
                 item_coords = self.canvas.coords(self.dragging_item)
                 if not item_coords: raise ValueError("Item has no coordinates")
                 item_center_x = item_coords[0]; self.drag_offset_x = canvas_x - item_center_x
                 self.canvas.tag_raise(self.dragging_item)
                 if 0 <= self.dragging_index < len(self.del_btn_ids):
                     dragged_del_btn_id = self.del_btn_ids[self.dragging_index]
                     if self.canvas.winfo_exists() and dragged_del_btn_id in self.canvas.find_all():
                          self.canvas.tag_raise(dragged_del_btn_id)
                 else: self.cancel_internal_drag()
            except (tk.TclError, ValueError, IndexError, Exception) as e:
                 self.cancel_internal_drag()
        else:
            self._on_frame_click(event)
            self.dragging_item = None; self.dragging_index = None

    def on_drag(self, event):
        if (self.organizer and self.organizer.is_external_dragging()) or self.dragging_item is None: return
        try:
            if not self.canvas or not self.canvas.winfo_exists(): self.cancel_internal_drag(); return

            if self.dragging_index is None or \
               not (0 <= self.dragging_index < len(self.items)) or \
               self.items[self.dragging_index] != self.dragging_item or \
               not (0 <= self.dragging_index < len(self.del_btn_ids)):
                 self.cancel_internal_drag(reposition=True); return

            canvas_x = self.canvas.canvasx(event.x)
            idx = self.dragging_index; current_item_id = self.dragging_item
            del_btn_id = self.del_btn_ids[idx]

            try:
                self.canvas.itemconfig(current_item_id)
                self.canvas.itemconfig(del_btn_id)
            except tk.TclError:
                 self.cancel_internal_drag(reposition=True); return


            item_coords = self.canvas.coords(current_item_id)
            if not item_coords: self.cancel_internal_drag(reposition=True); return

            current_y_center = item_coords[1]; new_x_center = canvas_x - self.drag_offset_x
            self.canvas.coords(current_item_id, new_x_center, current_y_center)
            btn_new_x = new_x_center + self.thumb_size[0] // 2 - 2
            btn_new_y = current_y_center - self.thumb_size[1] // 2 + 2
            self.canvas.coords(del_btn_id, btn_new_x, btn_new_y)
            self.canvas.tag_raise(current_item_id); self.canvas.tag_raise(del_btn_id)

            root_x, root_y = event.x_root, event.y_root
            try:
                 canvas_abs_x = self.canvas.winfo_rootx(); canvas_abs_y = self.canvas.winfo_rooty()
                 canvas_width = self.canvas.winfo_width(); canvas_height = self.canvas.winfo_height()
            except tk.TclError: self.cancel_internal_drag(reposition=True); return

            buffer = 5
            is_outside_canvas = not (canvas_abs_x - buffer <= root_x < canvas_abs_x + canvas_width + buffer and \
                                     canvas_abs_y - buffer <= root_y < canvas_abs_y + canvas_height + buffer)

            if is_outside_canvas:
                file_path_tuple_drag = self.images_data[idx]
                photo_image_ref = self.photos[idx]; source_item_id = self.dragging_item

                self.cancel_internal_drag(reposition=False)

                if self.organizer:
                    self.organizer.start_external_drag(
                        source_jour_frame=self, source_item_id=source_item_id, # Renamed
                        file_path_tuple=file_path_tuple_drag,
                        photo_image=photo_image_ref, event=event)
                return

            target_index = self._calculate_insert_index(new_x_center)
            if target_index != idx:
                try:
                    moved_item = self.items.pop(idx); moved_photo = self.photos.pop(idx)
                    moved_data_tuple = self.images_data.pop(idx); moved_del_btn = self.del_btn_ids.pop(idx)
                except IndexError: self.cancel_internal_drag(reposition=True); return

                actual_insert_index = target_index
                if target_index > idx:
                    actual_insert_index = target_index -1
                actual_insert_index = max(0, min(actual_insert_index, len(self.items)))


                self.items.insert(actual_insert_index, moved_item)
                self.photos.insert(actual_insert_index, moved_photo)
                self.images_data.insert(actual_insert_index, moved_data_tuple)
                self.del_btn_ids.insert(actual_insert_index, moved_del_btn)

                self.dragging_index = actual_insert_index
                self._reset_save_button_color(mark_unsaved=True)
                self.reposition_except_dragging()
        except (tk.TclError, ValueError, IndexError, Exception) as e:
             print(f"Error in on_drag (Jour {self.letter}): {e}") # Renamed
             traceback.print_exc()
             self.cancel_internal_drag(reposition=True)

    def reposition_except_dragging(self):
        if not self.canvas or not self.canvas.winfo_exists() or self.dragging_item is None: return

        if not (len(self.items) == len(self.del_btn_ids) == len(self.images_data) == len(self.photos)):
             print(f"Jour {self.letter}: Inconsistency in reposition_except_dragging. Rebuilding.") # Renamed
             self.rebuild_and_reposition()
             self.cancel_internal_drag(reposition=False); return

        y_center_img = self.canvas_height // 2
        current_x_center = self.margin + self.thumb_size[0] // 2
        current_dragging_item_id = self.dragging_item

        for i, item_id_in_list in enumerate(self.items):
            if item_id_in_list == current_dragging_item_id:
                current_x_center += self.thumb_size[0] + self.margin; continue

            del_btn_id_in_list = self.del_btn_ids[i]
            try:
                try: self.canvas.itemconfig(item_id_in_list); self.canvas.itemconfig(del_btn_id_in_list)
                except tk.TclError:
                    print(f"Jour {self.letter}: Item {item_id_in_list} or btn {del_btn_id_in_list} (index {i}) not on canvas in reposition_except_dragging. Rebuilding.") # Renamed
                    self.rebuild_and_reposition(); self.cancel_internal_drag(reposition=False); return

                target_x_img = current_x_center; target_y_img = y_center_img
                target_x_btn = target_x_img + self.thumb_size[0] // 2 - 2
                target_y_btn = target_y_img - self.thumb_size[1] // 2 + 2

                self.canvas.coords(item_id_in_list, target_x_img, target_y_img)
                self.canvas.coords(del_btn_id_in_list, target_x_btn, target_y_btn)
                current_x_center += self.thumb_size[0] + self.margin
            except Exception as e:
                 print(f"Error repositioning non-dragged item {item_id_in_list} in Jour {self.letter}: {e}. Rebuilding.") # Renamed
                 traceback.print_exc()
                 self.rebuild_and_reposition(); self.cancel_internal_drag(reposition=False); return

        self.update_scroll_region()

    def on_release(self, event):
        if self.organizer and self.organizer.is_external_dragging():
            if self.dragging_item is not None:
                 self.cancel_internal_drag(reposition=False)
            return

        was_internal_dragging = self.dragging_item is not None
        if was_internal_dragging:
            self.dragging_item = None; self.dragging_index = None; self.drag_offset_x = 0
            self.reposition_all()
            if self.update_callback: self.canvas.after_idle(self.update_callback)

    def cancel_internal_drag(self, reposition=True):
         was_dragging = self.dragging_item is not None
         self.dragging_item = None; self.dragging_index = None; self.drag_offset_x = 0
         if was_dragging and reposition:
             if self.canvas and self.canvas.winfo_exists(): self.reposition_all()

    def save(self):
        folder = os.path.join(self.base_dir, f"jour {self.letter}") # Use "jour" in folder name
        save_successful = True

        if not self.images_data:
            if os.path.isdir(folder):
                try:
                    for item in os.listdir(folder):
                        item_path = os.path.join(folder, item)
                        if os.path.isfile(item_path) or os.path.islink(item_path): os.remove(item_path)
                except Exception: pass
            if self.save_btn and self.save_btn.winfo_exists():
                self.save_btn.config(bg="lightgreen")
                self.save_btn.after(2500, lambda: self._reset_save_button_color(mark_unsaved=False))

            if self.organizer:
                self.organizer.notify_jour_frame_saved(self, saved_folder=folder, is_empty=True) # Renamed
            return True

        try:
            os.makedirs(folder, exist_ok=True)
            error_messages = []
            try:
                for existing_file in os.listdir(folder):
                    existing_file_path = os.path.join(folder, existing_file)
                    if os.path.isfile(existing_file_path) or os.path.islink(existing_file_path):
                         os.remove(existing_file_path)
            except Exception as list_e:
                 messagebox.showwarning("Warning Saving",f"Could not list or clear folder before saving: {folder}\n{list_e}", parent=self.frame)

            for i, (display_path, original_ref_path) in enumerate(self.images_data):
                try:
                    original_basename_for_naming = os.path.basename(original_ref_path)
                    _root_for_naming, ext_for_naming = os.path.splitext(original_basename_for_naming)
                    safe_original_root_for_naming = safe_encode_basename(_root_for_naming)
                    new_name = f"{self.letter}{i+1}{FILENAME_DELIMITER}{safe_original_root_for_naming}{ext_for_naming}"
                    dest_path = os.path.join(folder, new_name)
                    shutil.copy2(display_path, dest_path)
                except Exception as e:
                    err_msg = f"  ERROR copying '{os.path.basename(display_path)}' -> '{new_name}': {e}"
                    error_messages.append(err_msg); save_successful = False

            if not error_messages:
               if self.save_btn and self.save_btn.winfo_exists():
                    self.save_btn.config(bg="lightgreen")
                    self.save_btn.after(2500, lambda: self._reset_save_button_color(mark_unsaved=False))
            else:
               error_summary = "\n".join(error_messages[:5]) + ("\n..." if len(error_messages) > 5 else "")
               messagebox.showerror("Saving Errors", f"{len(error_messages)} error(s) occurred while saving for Jour {self.letter}.\nDetails:\n{error_summary}", parent=self.frame) # Renamed
               self._reset_save_button_color(mark_unsaved=False)

            if self.organizer and save_successful:
                self.organizer.notify_jour_frame_saved(self, saved_folder=folder, is_empty=False) # Renamed
            return save_successful
        except Exception as e:
            messagebox.showerror("Saving Error", f"A critical error occurred while trying to save to folder:\n{folder}\n\n{e}", parent=self.frame)
            self._reset_save_button_color(mark_unsaved=False); return False

    def _reset_save_button_color(self, mark_unsaved=True):
        try:
            if self.save_btn and self.save_btn.winfo_exists():
                if mark_unsaved:
                    self.save_btn.config(bg="gold")
                else:
                    self.save_btn.config(bg=self.save_btn_original_bg)
        except tk.TclError: pass


    def close_jour(self): # Renamed
        if self.organizer: self.organizer.close_jour_frame(self) # Renamed

    def get_usage_data(self):
        usage = {}
        color_idx = self.index % len(JOUR_COLORS); color = JOUR_COLORS[color_idx] # Use JOUR_COLORS
        for i, (display_path, original_ref_path) in enumerate(self.images_data):
            label = f"{self.letter}{i+1}"
            usage[original_ref_path] = (label, color, display_path, self.letter)
        return usage

    def destroy(self):
        self.cancel_internal_drag(reposition=False)
        if self.canvas and self.canvas.winfo_exists():
            try:
                win_items = self.canvas.find_withtag('window')
                if win_items:
                    for win_id in win_items:
                        try:
                            widget_path = self.canvas.itemcget(win_id, "-window")
                            if widget_path:
                                widget = self.canvas.nametowidget(widget_path)
                                if widget and widget.winfo_exists(): widget.destroy()
                        except Exception: pass
                self.canvas.delete("all")
            except Exception: pass

        if self.frame and self.frame.winfo_exists():
            try: self.frame.destroy(); self.frame = None
            except Exception: pass

        self.images_data.clear(); self.photos.clear(); self.items.clear(); self.del_btn_ids.clear()
        self.organizer = None; self.update_callback = None; self.canvas = None
        self.label = None; self.save_btn = None; self.close_btn = None; self.crop_btn = None

# --- LoadingScreen (PublicationOrganizer) ---
class PubOrgLoadingScreen:
    def __init__(self, parent, total):
        self.top = tk.Toplevel(parent)
        self.top.title("Chargement...")
        self.top.grab_set(); self.top.protocol("WM_DELETE_WINDOW", lambda: None)
        self.top.resizable(False, False); self.center_window(parent)
        self.top.lift(); self.top.attributes("-topmost", True)
        self.progress = ttk.Progressbar(self.top, orient="horizontal", length=350, mode="determinate", maximum=total)
        self.progress.pack(pady=20, padx=25)
        self.label = tk.Label(self.top, text=f"Chargement de 0 / {total} images...")
        self.label.pack(pady=(0, 10)); self.total = total; self.top.update()

    def center_window(self, parent):
        try:
            self.top.update_idletasks();
            win_w = self.top.winfo_width(); win_h = self.top.winfo_height()
            if parent and parent.winfo_exists() and parent.winfo_viewable():
                parent_geo = parent.winfo_geometry();
                parent_parts = parent_geo.split('+')
                parent_w_h = parent_parts[0].split('x')
                parent_w = int(parent_w_h[0]); parent_h = int(parent_w_h[1])
                parent_x = int(parent_parts[1]); parent_y = int(parent_parts[2])
                x = parent_x + (parent_w // 2) - (win_w // 2)
                y = parent_y + (parent_h // 2) - (win_h // 2)
            else:
                 screen_w = self.top.winfo_screenwidth(); screen_h = self.top.winfo_screenheight()
                 x = (screen_w // 2) - (win_w // 2); y = (screen_h // 2) - (win_h // 2)
            screen_w = self.top.winfo_screenwidth(); screen_h = self.top.winfo_screenheight()
            x = max(0, min(x, screen_w - win_w)); y = max(0, min(y, screen_h - win_h))
            self.top.geometry(f"+{x}+{y}")
        except Exception: self.top.geometry("400x100")

    def update(self, value):
        if not self.top or not self.top.winfo_exists(): return
        try:
            self.progress["value"] = value
            self.label.config(text=f"Chargement de {value} / {self.total} images...")
            self.top.update()
        except tk.TclError: self.top = None

    def destroy(self):
        if self.top and self.top.winfo_exists():
            try: self.top.grab_release(); self.top.destroy()
            except tk.TclError: pass
        self.top = None

# --- ProgrammationPage ---
class ProgrammationPage(tk.Frame):
    def __init__(self, parent, organizer_app):
        super().__init__(parent)
        self.organizer_app = organizer_app
        self.base_dir = self.organizer_app.base_dir
        self.schedule_file_path = os.path.join(self.base_dir, SCHEDULE_FILENAME)
        self.schedule_data = {}  # {"YYYY-MM-DD": {"A": {"label": "Pub A"}, ...}}

        self.current_date = datetime.date.today()
        self.day_frames = {}
        self.drag_data = {}
        self.context_preview_window = None # MODIFIED: Renamed from hover_preview_window
        self.calendar_thumb_cache = {} # For small in-cell previews

        self._init_ui()
        self.load_schedule()
        self.build_calendar_ui()

    def _init_ui(self):
        self.config(bg="white")
        header_frame = tk.Frame(self, bg="lightgray")
        header_frame.pack(fill=tk.X, pady=5)

        tk.Button(header_frame, text="<< Année Préc.", command=lambda: self.change_month(-12)).pack(side=tk.LEFT, padx=5)
        tk.Button(header_frame, text="< Mois Préc.", command=lambda: self.change_month(-1)).pack(side=tk.LEFT, padx=5)
        self.month_year_label = tk.Label(header_frame, text="", font=("Helvetica", 14, "bold"), bg="lightgray")
        self.month_year_label.pack(side=tk.LEFT, expand=True)
        tk.Button(header_frame, text="Mois Suiv. >", command=lambda: self.change_month(1)).pack(side=tk.RIGHT, padx=5)
        tk.Button(header_frame, text="Année Suiv. >>", command=lambda: self.change_month(12)).pack(side=tk.RIGHT, padx=5)
        tk.Button(header_frame, text="Aujourd'hui", command=self.go_to_today).pack(side=tk.RIGHT, padx=10)

        self.calendar_grid_frame = tk.Frame(self, bg="white")
        self.calendar_grid_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def go_to_today(self):
        self.current_date = datetime.date.today()
        self.build_calendar_ui()

    def change_month(self, month_delta):
        current_year, current_month = self.current_date.year, self.current_date.month
        new_month_abs = (current_month - 1) + month_delta
        new_year = current_year + new_month_abs // 12
        new_month = new_month_abs % 12 + 1
        try:
            self.current_date = self.current_date.replace(year=new_year, month=new_month)
        except ValueError:
            _, last_day_of_new_month = calendar.monthrange(new_year, new_month)
            self.current_date = self.current_date.replace(year=new_year, month=new_month, day=last_day_of_new_month)
        self.build_calendar_ui()

    def build_calendar_ui(self):
        for widget in self.calendar_grid_frame.winfo_children():
            widget.destroy()
        self.day_frames.clear()

        year = self.current_date.year
        month = self.current_date.month

        try:
            month_name_str = calendar.month_name[month]
        except Exception:
            month_name_str = calendar.month_name[month]
        self.month_year_label.config(text=f"{month_name_str} {year}")

        cal = calendar.Calendar(firstweekday=calendar.MONDAY)
        month_days = cal.monthdatescalendar(year, month)

        days_of_week_fr = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        for col, day_name in enumerate(days_of_week_fr):
            lbl = tk.Label(self.calendar_grid_frame, text=day_name, font=("Helvetica", 10, "bold"), bg="lightgrey", relief="ridge", width=10)
            lbl.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)

        for r_idx, week in enumerate(month_days):
            for c_idx, day_date_obj in enumerate(week):
                day_str_key = day_date_obj.strftime("%Y-%m-%d")
                # MODIFIED: Reduced height for smaller cells
                day_outer_frame = tk.Frame(self.calendar_grid_frame, relief="solid", borderwidth=1, bg="white", height=70)
                day_outer_frame.grid(row=r_idx + 1, column=c_idx, sticky="nsew", padx=1, pady=1)
                day_outer_frame.grid_propagate(False)
                self.calendar_grid_frame.grid_rowconfigure(r_idx + 1, weight=1)
                self.calendar_grid_frame.grid_columnconfigure(c_idx, weight=1)

                day_number_lbl = tk.Label(day_outer_frame, text=str(day_date_obj.day), font=("Helvetica", 9), anchor="nw", bg="white")
                if day_date_obj.month != month:
                    day_number_lbl.config(fg="gray")
                elif day_date_obj == datetime.date.today():
                    day_number_lbl.config(font=("Helvetica", 9, "bold"), fg="blue")
                day_number_lbl.pack(side=tk.TOP, fill=tk.X, padx=2, pady=2)

                day_content_frame = tk.Frame(day_outer_frame, bg="white")
                day_content_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                self.day_frames[day_str_key] = day_content_frame

                # MODIFIED: Removed ButtonRelease-1 binding that called _on_drop directly
                # Drop logic is now handled by _on_drop_anywhere via root binding

                if day_str_key in self.schedule_data:
                    items_on_day = self.schedule_data[day_str_key]
                    sorted_letters = sorted(items_on_day.keys())
                    for letter in sorted_letters:
                        item_data = items_on_day[letter]
                        label_text = item_data.get("label", f"Jour {letter}")
                        color_idx_corrected = (ord(letter.upper()) - ord('A')) % len(JOUR_COLORS)
                        bg_color = JOUR_COLORS[color_idx_corrected]

                        pub_item_frame = tk.Frame(day_content_frame, bg=bg_color, relief="raised", borderwidth=1)
                        pub_item_frame.pack(fill=tk.X, pady=1, padx=1)

                        pub_text_label = tk.Label(pub_item_frame, text=label_text, bg=bg_color, fg="white", padx=3, pady=1, font=("Arial", 8))
                        pub_text_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

                        thumb_label = tk.Label(pub_item_frame, bg=bg_color, width=CALENDAR_THUMB_SIZE[0], height=CALENDAR_THUMB_SIZE[1])
                        thumb_label.pack(side=tk.RIGHT, padx=(2,0))
                        self._load_calendar_thumb(thumb_label, letter)

                        widgets_to_bind = [pub_item_frame, pub_text_label, thumb_label]
                        for widget in widgets_to_bind:
                            widget.bind("<ButtonPress-1>",
                                           lambda e, ds=day_str_key, l=letter, item_widget=pub_item_frame: self._on_drag_start(e, ds, l, item_widget))
                            # MODIFIED: Changed from Enter/Leave to Button-3 (Right-Click)
                            right_click_event = "<Button-3>"
                            if sys.platform == "darwin": # macOS uses Button-2 for context menu sometimes
                                right_click_event = "<Button-2>"
                            widget.bind(right_click_event,
                                           lambda e, l=letter, ds=day_str_key: self._show_context_preview(e, l, ds))
                            # _hide_context_preview is now primarily handled by _show_context_preview or by leaving the preview window

    def _load_calendar_thumb(self, thumb_label_widget, jour_letter):
        if not self.organizer_app or not self.organizer_app.base_dir:
            return
        jour_folder_path = os.path.join(self.organizer_app.base_dir, f"jour {jour_letter}")
        image_path = None
        try:
            file_pattern = os.path.join(jour_folder_path, f"{jour_letter}1{FILENAME_DELIMITER}*")
            possible_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']
            found_files = []
            for ext in possible_extensions:
                found_files.extend(glob.glob(file_pattern + ext, recursive=False))
                if found_files: break
            if found_files:
                image_path = sorted(found_files)[0]
        except Exception as e:
            print(f"Error globbing for calendar thumb: {e}")

        if image_path and os.path.exists(image_path):
            if image_path in self.calendar_thumb_cache:
                thumb_photo = self.calendar_thumb_cache[image_path]
            else:
                try:
                    img = Image.open(image_path)
                    img = ImageOps.exif_transpose(img)
                    img.thumbnail(CALENDAR_THUMB_SIZE, Image.Resampling.LANCZOS)
                    bg_for_thumb = Image.new('RGB', CALENDAR_THUMB_SIZE, thumb_label_widget.cget("bg"))
                    paste_x = (CALENDAR_THUMB_SIZE[0] - img.width) // 2
                    paste_y = (CALENDAR_THUMB_SIZE[1] - img.height) // 2
                    if img.mode == 'RGBA':
                        bg_for_thumb.paste(img, (paste_x, paste_y), mask=img.split()[3])
                    elif img.mode == 'P' and 'transparency' in img.info:
                        img_rgba = img.convert('RGBA')
                        bg_for_thumb.paste(img_rgba, (paste_x, paste_y), mask=img_rgba.split()[3])
                    else:
                        bg_for_thumb.paste(img.convert('RGB'), (paste_x, paste_y))
                    thumb_photo = ImageTk.PhotoImage(bg_for_thumb)
                    self.calendar_thumb_cache[image_path] = thumb_photo
                except Exception as e:
                    print(f"Error creating calendar thumb for {image_path}: {e}")
                    thumb_photo = None
            if thumb_photo:
                thumb_label_widget.config(image=thumb_photo, width=CALENDAR_THUMB_SIZE[0], height=CALENDAR_THUMB_SIZE[1])
                thumb_label_widget.image = thumb_photo
                return
        thumb_label_widget.config(image='', text="N/A", fg="white", font=("Arial", 7))
        thumb_label_widget.image = None

    # MODIFIED: Renamed from _show_hover_preview
    def _show_context_preview(self, event, jour_letter, date_str):
        if self.context_preview_window and self.context_preview_window.winfo_exists():
            self.context_preview_window.destroy()
        self.context_preview_window = None

        if not self.organizer_app or not self.organizer_app.base_dir:
            return

        jour_folder_path = os.path.join(self.organizer_app.base_dir, f"jour {jour_letter}")
        image_files = []
        if os.path.isdir(jour_folder_path):
            try:
                all_files_in_folder = []
                for ext in ('*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp', '*.tiff'):
                    all_files_in_folder.extend(glob.glob(os.path.join(jour_folder_path, ext)))
                all_files_in_folder.sort()
                image_files = all_files_in_folder[:MAX_HOVER_PREVIEWS]
            except Exception as e:
                print(f"Error listing images for context preview: {e}")

        if not image_files:
            return

        self.context_preview_window = tk.Toplevel(self.organizer_app.root)
        self.context_preview_window.wm_overrideredirect(True)
        self.context_preview_window.wm_attributes("-topmost", True)
        # MODIFIED: Bind Leave on the preview window itself to hide it
        self.context_preview_window.bind("<Leave>", self._hide_context_preview)


        preview_main_frame = tk.Frame(self.context_preview_window, bg="black", bd=1, relief="solid")
        preview_main_frame.pack(fill=tk.BOTH, expand=True)
        title_label = tk.Label(preview_main_frame, text=f"Aperçu Jour {jour_letter} ({date_str})", bg="black", fg="white", font=("Arial", 9, "bold"))
        title_label.pack(pady=(2,4))
        thumbs_frame = tk.Frame(preview_main_frame, bg="black")
        thumbs_frame.pack(padx=5, pady=5)
        photos_for_context = []

        for img_path in image_files:
            try:
                img = Image.open(img_path)
                img = ImageOps.exif_transpose(img)
                img.thumbnail(CALENDAR_HOVER_THUMB_SIZE, Image.Resampling.LANCZOS)
                bg_hover_thumb = Image.new('RGB', CALENDAR_HOVER_THUMB_SIZE, "black")
                paste_x = (CALENDAR_HOVER_THUMB_SIZE[0] - img.width) // 2
                paste_y = (CALENDAR_HOVER_THUMB_SIZE[1] - img.height) // 2
                if img.mode == 'RGBA':
                    bg_hover_thumb.paste(img, (paste_x, paste_y), mask=img.split()[3])
                elif img.mode == 'P' and 'transparency' in img.info:
                    img_rgba = img.convert('RGBA')
                    bg_hover_thumb.paste(img_rgba, (paste_x, paste_y), mask=img_rgba.split()[3])
                else:
                    bg_hover_thumb.paste(img.convert('RGB'), (paste_x, paste_y))
                photo = ImageTk.PhotoImage(bg_hover_thumb)
                photos_for_context.append(photo)
                lbl = tk.Label(thumbs_frame, image=photo, bg="black")
                lbl.pack(side=tk.LEFT, padx=2)
            except Exception as e:
                print(f"Error loading image for context preview {img_path}: {e}")

        if not photos_for_context:
            self.context_preview_window.destroy()
            self.context_preview_window = None
            return

        self.context_preview_window._photos = photos_for_context
        self.context_preview_window.update_idletasks()
        x = event.x_root + 15
        y = event.y_root + 10
        screen_w = self.context_preview_window.winfo_screenwidth()
        screen_h = self.context_preview_window.winfo_screenheight()
        win_w = self.context_preview_window.winfo_width()
        win_h = self.context_preview_window.winfo_height()
        if x + win_w > screen_w: x = screen_w - win_w - 5
        if y + win_h > screen_h: y = screen_h - win_h - 5
        if x < 0 : x = 5
        if y < 0 : y = 5
        self.context_preview_window.geometry(f"+{x}+{y}")

    # MODIFIED: Renamed from _hide_hover_preview
    def _hide_context_preview(self, event):
        if self.context_preview_window and self.context_preview_window.winfo_exists():
            # Check if mouse is still over the preview window itself
            # This check is important if the Leave event is on the main widget
            # but here it's on the preview window, so any leave means hide.
            # if self.context_preview_window.winfo_containing(event.x_root, event.y_root) == self.context_preview_window:
            #     return
            self.context_preview_window.destroy()
        self.context_preview_window = None

    def _on_drag_start(self, event, date_str, letter, item_widget):
        if self.drag_data.get("window"):
            return
        self.drag_data["source_date_str"] = date_str
        self.drag_data["source_letter"] = letter
        self.drag_data["source_data"] = self.schedule_data[date_str][letter]
        try:
            text_label_widget = next(c for c in item_widget.winfo_children() if isinstance(c, tk.Label) and hasattr(c, 'cget') and 'text' in c.keys())
            self.drag_data["widget_text"] = text_label_widget.cget("text")
        except (StopIteration, tk.TclError):
            self.drag_data["widget_text"] = f"Jour {letter}"
        self.drag_data["widget_bg"] = item_widget.cget("background")

        self.drag_data["window"] = tk.Toplevel(self.organizer_app.root)
        self.drag_data["window"].overrideredirect(True)
        self.drag_data["window"].attributes("-topmost", True)
        try: self.drag_data["window"].attributes("-alpha", 0.7)
        except tk.TclError: pass
        drag_label = tk.Label(self.drag_data["window"], text=self.drag_data["widget_text"],
                              bg=self.drag_data["widget_bg"], fg="white", relief="solid", borderwidth=1, padx=5, pady=2)
        drag_label.pack()
        x, y = event.x_root, event.y_root
        self.drag_data["window"].geometry(f"+{x+10}+{y+5}")
        self.organizer_app.root.bind("<Motion>", self._on_drag_motion, add='+')
        self.organizer_app.root.bind("<ButtonRelease-1>", self._on_drop_anywhere, add='+')

    def _on_drag_motion(self, event):
        if not self.drag_data.get("window") or not self.drag_data["window"].winfo_exists():
            self._cleanup_drag(); return
        x, y = event.x_root, event.y_root
        self.drag_data["window"].geometry(f"+{x+10}+{y+5}")
        for df_str, frame_widget in self.day_frames.items():
            if frame_widget.winfo_exists():
                try:
                    widget_x = frame_widget.winfo_rootx()
                    widget_y = frame_widget.winfo_rooty()
                    widget_w = frame_widget.winfo_width()
                    widget_h = frame_widget.winfo_height()
                    if widget_x <= x < widget_x + widget_w and \
                       widget_y <= y < widget_y + widget_h:
                        frame_widget.config(bg="lightyellow")
                    else:
                        frame_widget.config(bg="white")
                except tk.TclError: pass

    def _cleanup_drag(self):
        if self.drag_data.get("window"):
            if self.drag_data["window"].winfo_exists():
                self.drag_data["window"].destroy()
        try:
            if self.organizer_app and self.organizer_app.root and self.organizer_app.root.winfo_exists():
                self.organizer_app.root.unbind("<Motion>")
                self.organizer_app.root.unbind("<ButtonRelease-1>")
        except tk.TclError: pass
        for frame_widget in self.day_frames.values():
            if frame_widget.winfo_exists():
                try: frame_widget.config(bg="white")
                except tk.TclError: pass
        self.drag_data.clear()

    # MODIFIED: This method now handles the full drop logic.
    def _on_drop_anywhere(self, event):
        if not self.drag_data.get("source_date_str"): # No active drag
            self._cleanup_drag()
            return

        target_date_key = None
        # Identify if dropped on a valid day_content_frame
        for day_key, frame_widget in self.day_frames.items():
            if frame_widget.winfo_exists():
                try:
                    widget_x = frame_widget.winfo_rootx()
                    widget_y = frame_widget.winfo_rooty()
                    widget_w = frame_widget.winfo_width()
                    widget_h = frame_widget.winfo_height()
                    if widget_x <= event.x_root < widget_x + widget_w and \
                       widget_y <= event.y_root < widget_y + widget_h:
                        target_date_key = day_key
                        break
                except tk.TclError: continue

        if target_date_key: # Dropped on a valid day cell
            source_date = self.drag_data["source_date_str"]
            source_letter = self.drag_data["source_letter"]
            source_item_data = self.drag_data["source_data"]

            if source_date == target_date_key:
                # Dropped on the same day, no actual data change needed
                # but rebuild UI to reset any visual artifacts
                self.build_calendar_ui()
            else:
                # Move item logic
                if source_date in self.schedule_data and source_letter in self.schedule_data[source_date]:
                    del self.schedule_data[source_date][source_letter]
                    if not self.schedule_data[source_date]:
                        del self.schedule_data[source_date]

                if target_date_key not in self.schedule_data:
                    self.schedule_data[target_date_key] = {}
                self.schedule_data[target_date_key][source_letter] = source_item_data

                self.save_schedule()
                self.build_calendar_ui()
                messagebox.showinfo("Programmation mise à jour",
                                    f"Publication '{source_item_data.get('label', 'Jour '+source_letter)}' déplacée du {source_date} au {target_date_key}.",
                                    parent=self)
        # else: Dropped outside any valid day cell, no data change, just cleanup

        self._cleanup_drag()

    # REMOVED: _on_drop method. Its logic is now integrated into _on_drop_anywhere.

    def load_schedule(self):
        if os.path.exists(self.schedule_file_path):
            try:
                with open(self.schedule_file_path, 'r', encoding='utf-8') as f:
                    self.schedule_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Erreur chargement programmation: {e}")
                self.schedule_data = {}
        else:
            self.schedule_data = {}

    def save_schedule(self):
        try:
            with open(self.schedule_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.schedule_data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            print(f"Erreur sauvegarde programmation: {e}")
            messagebox.showerror("Erreur Sauvegarde", f"Impossible de sauvegarder la programmation:\n{e}", parent=self)

    def add_or_update_publication_for_date(self, date_obj, jour_letter, label_text):
        date_str = date_obj.strftime("%Y-%m-%d")
        if date_str not in self.schedule_data:
            self.schedule_data[date_str] = {}
        self.schedule_data[date_str][jour_letter] = {"label": label_text}
        self.save_schedule()
        if self.winfo_exists():
            self.build_calendar_ui()

    def remove_publication_for_date(self, date_obj, jour_letter):
        date_str = date_obj.strftime("%Y-%m-%d")
        if date_str in self.schedule_data and jour_letter in self.schedule_data[date_str]:
            del self.schedule_data[date_str][jour_letter]
            if not self.schedule_data[date_str]:
                del self.schedule_data[date_str]
            self.save_schedule()
            if self.winfo_exists():
                self.build_calendar_ui()

    def get_scheduled_letters_for_date(self, date_obj):
        date_str = date_obj.strftime("%Y-%m-%d")
        if date_str in self.schedule_data:
            return list(self.schedule_data[date_str].keys())
        return []


# --- PublicationOrganizer ---
class PublicationOrganizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Organisateur de Publications")
        self.current_thumb_size = (200, 200)

        try: self.root.state('zoomed')
        except tk.TclError:
            initial_width=1200; initial_height=850
            try:
                s_w=root.winfo_screenwidth(); s_h=root.winfo_screenheight()
                c_x=max(0,int(s_w/2-initial_width/2)); c_y=max(0,int(s_h/2-initial_height/2))
                self.root.geometry(f"{initial_width}x{initial_height}+{c_x}+{c_y}")
            except tk.TclError: self.root.geometry(f"{initial_width}x{initial_height}")

        self.root.minsize(1000, 700)
        self.root.withdraw()

        self._initializing = True; self.selected_paths = []; self.images_to_load = []
        self.base_dir = "."
        self.min_thumb_size = (50, 50); self.max_thumb_size = (300, 300)
        self.zoom_step = 25;
        self.grid_margin = 10; self.grid_items = []; self.grid_items_dict = {}
        self._reflow_job = None

        self.jour_frames = [] # Renamed from self.corridors
        self.current_jour_frame = None # Renamed from self.current_corridor
        self.permanent_usage_map = {}; self.next_jour_index = 0 # Renamed
        self.jour_folder_pattern = re.compile(r"^jour ([a-zA-Z])$", re.IGNORECASE) # Updated pattern
        self.existing_jour_data = {} # Renamed

        self._external_bindings_active = False; self.external_drag_window = None
        self.external_drag_photo = None; self.external_drag_path_tuple = None
        self.external_drag_source_jour_frame = None; self.external_drag_source_item_id = None # Renamed
        self.selection_file_path = None

        self.notebook = ttk.Notebook(self.root)

        self.main_editor_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(self.main_editor_frame, text='Éditeur de Publications')

        self.programmation_tab_frame = ttk.Frame(self.notebook, padding=5)
        self.programmation_page = None

        self.notebook.pack(expand=True, fill='both')

        try:
            if not self.select_images(): self.exit_app("Aucune image sélectionnée."); return

            original_import_parent_folder_path = "."
            if self.selected_paths:
                original_import_parent_folder_path = os.path.normpath(os.path.dirname(self.selected_paths[0]))

            self.filter_selected_images(original_import_base_dir=original_import_parent_folder_path)
            if not self.images_to_load: self.exit_app("Aucune image à afficher (filtrées)."); return

            project_name_base = "default_project"
            if self.selected_paths:
                first_image_path = self.selected_paths[0]
                first_image_filename = os.path.basename(first_image_path)
                first_image_base, _ = os.path.splitext(first_image_filename)
                if first_image_base:
                    project_name_base = first_image_base

            try:
                desktop_path = self._get_desktop_path()
                publications_root_path = os.path.join(desktop_path, "publications")
                os.makedirs(publications_root_path, exist_ok=True)
                safe_project_name = re.sub(r'[<>:"/\\|?*]', '_', project_name_base)
                safe_project_name = safe_project_name[:100]
                if not safe_project_name: safe_project_name = "default_project"
                self.base_dir = os.path.join(publications_root_path, safe_project_name)
                os.makedirs(self.base_dir, exist_ok=True)
                print(f"[*] Dossier de publication défini sur : {self.base_dir}")
            except OSError as e:
                self.exit_app(f"Erreur création dossier de publication '{safe_project_name}' sur le bureau:\n{e}\nVérifiez permissions/espace.")
                return

            self.programmation_page = ProgrammationPage(self.programmation_tab_frame, self)
            self.programmation_page.pack(expand=True, fill='both')
            self.notebook.add(self.programmation_tab_frame, text='Programmation')


            self.selection_file_path = os.path.join(self.base_dir, "selection_state.json")

            self.determine_start_index()
            self.load_existing_jour_frames_data() # Renamed

            self._create_ui_elements()
            loading_successful = self.load_grid_items()

            if loading_successful:
                self._pack_ui_elements(); self._bind_scroll_events(); self._bind_configure_events()
                self.sort_grid_items_and_reflow()
                self.mark_grid_items_from_existing_data()
                self.create_and_populate_existing_jour_frames() # Renamed

                if not self.jour_frames and self.next_jour_index < 26: # Renamed
                     self.add_jour_frame() # Renamed
                if not self.current_jour_frame and self.jour_frames: # Renamed
                     self.set_current_jour_frame(self.jour_frames[0]) # Renamed

                self.reflow_grid()
                self.root.protocol("WM_DELETE_WINDOW", self.on_close_window)
                self._initializing = False; self._update_stats_label()
                self.root.deiconify(); self.root.after(50, self.root.lift); self.root.after(100, self.root.focus_force)
            else: self.exit_app("Échec du chargement des images dans la grille."); return
        except Exception as init_error:
            traceback.print_exc()
            messagebox.showerror("Erreur d'Initialisation",f"Erreur critique lors de l'initialisation:\n\n{init_error}", parent=self.root if self.root else None)
            self.safe_destroy(); return

    def _get_desktop_path(self):
        home = os.path.expanduser("~")
        possible_desktop_names = ["Desktop", "Bureau"]
        for name in possible_desktop_names:
            path = os.path.join(home, name)
            if os.path.isdir(path):
                return path
        return os.path.join(home, "Desktop")


    def exit_app(self, message):
        parent_for_msg = self.root if self.root and self.root.winfo_exists() and self.root.winfo_viewable() else None
        messagebox.showinfo("Information", f"{message}\nL'application va se fermer.", parent=parent_for_msg)
        if self.root: self.root.after_idle(self.safe_destroy)

    def _create_ui_elements(self):
        try:
            default_bg = self.root.cget('bg')
        except tk.TclError:
            default_bg = "SystemButtonFace" if sys.platform == "win32" else "#D9D9D9"

        self.zoom_control_frame = tk.Frame(self.main_editor_frame, bg=default_bg)
        tk.Label(self.zoom_control_frame, text="Affichage Grille:", bg=default_bg).pack(side=tk.LEFT, padx=(10, 5))
        self.sort_options = {
            "Nom (A-Z)": ("name", False), "Nom (Z-A)": ("name", True),
            "Date Prise (Plus Récente)": ("date", True), "Date Prise (Plus Ancienne)": ("date", False)
        }
        self.sort_var = tk.StringVar(value="Nom (A-Z)")
        tk.Label(self.zoom_control_frame, text="Trier par:", bg=default_bg).pack(side=tk.LEFT, padx=(10,2))
        self.sort_combobox = ttk.Combobox(self.zoom_control_frame, textvariable=self.sort_var, values=list(self.sort_options.keys()), state="readonly", width=23)
        self.sort_combobox.bind("<<ComboboxSelected>>", self.on_sort_option_changed)
        self.zoom_out_btn = tk.Button(self.zoom_control_frame, text="-", command=self._zoom_out, font=("Arial", 10, "bold"), width=2, height=1, relief="raised")
        self.zoom_in_btn = tk.Button(self.zoom_control_frame, text="+", command=self._zoom_in, font=("Arial", 10, "bold"), width=2, height=1, relief="raised")
        self.zoom_label = tk.Label(self.zoom_control_frame, text=f"{self.current_thumb_size[0]}px", width=5, bg=default_bg)
        self.stats_label = tk.Label(self.zoom_control_frame, text="Grille: 0 | Jours: 0", bg=default_bg, font=("Arial", 9)) # Renamed "Couloirs" to "Jours"

        self.grid_frame=tk.Frame(self.main_editor_frame, bg="darkgrey")
        self.grid_scrollbar=tk.Scrollbar(self.grid_frame,orient=tk.VERTICAL)
        self.grid_canvas=tk.Canvas(self.grid_frame, bg="lightgrey", bd=0, highlightthickness=0, yscrollcommand=self.grid_scrollbar.set)
        self.grid_scrollbar.config(command=self.grid_canvas.yview)
        self.grid_inner_frame=tk.Frame(self.grid_canvas, bg=self.grid_canvas.cget('bg'))
        self.grid_inner_frame_id=self.grid_canvas.create_window((0,0), window=self.grid_inner_frame, anchor="nw", tags="inner_frame")

        self.jour_frames_area=tk.LabelFrame(self.main_editor_frame, text="Jours de Publication", padx=5, pady=5, bg=default_bg) # Renamed
        self.jour_frames_scrollbar=tk.Scrollbar(self.jour_frames_area,orient=tk.VERTICAL) # Renamed
        self.jour_frames_canvas=tk.Canvas(self.jour_frames_area, bd=0, highlightthickness=0, bg=default_bg, yscrollcommand=self.jour_frames_scrollbar.set) # Renamed
        self.jour_frames_scrollbar.config(command=self.jour_frames_canvas.yview) # Renamed
        self.jour_frames_container=tk.Frame(self.jour_frames_canvas, bg=default_bg) # Renamed. This is parent_frame for JourFrame
        self.jour_frames_container_id=self.jour_frames_canvas.create_window((0,0), window=self.jour_frames_container, anchor="nw", tags="jour_frames_container") # Renamed

        self.button_holder_frame = tk.Frame(self.jour_frames_container, bg=default_bg)
        self.save_all_button = tk.Button(self.button_holder_frame, text="💾 Tout Enregistrer", command=self.save_all_jour_frames) # Renamed
        self.add_jour_frame_button = tk.Button(self.button_holder_frame, text="➕ Ajouter Jour", command=self.add_jour_frame) # Renamed

    def _pack_ui_elements(self):
        self.zoom_control_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5,0))
        self.sort_combobox.pack(side=tk.LEFT, padx=(0,15))
        self.stats_label.pack(side=tk.RIGHT, padx=(10, 10))
        self.zoom_in_btn.pack(side=tk.RIGHT, padx=(0, 5));
        self.zoom_label.pack(side=tk.RIGHT, padx=5);
        self.zoom_out_btn.pack(side=tk.RIGHT)
        self.grid_frame.pack(side=tk.TOP,fill=tk.BOTH,expand=True,padx=5,pady=5)
        self.grid_scrollbar.pack(side=tk.RIGHT,fill=tk.Y); self.grid_canvas.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        self.jour_frames_area.pack(side=tk.BOTTOM,fill=tk.X,expand=False,padx=5,pady=(0,5)) # Renamed
        self.jour_frames_scrollbar.pack(side=tk.RIGHT,fill=tk.Y); self.jour_frames_canvas.pack(side=tk.LEFT,fill=tk.BOTH,expand=True) # Renamed
        self.button_holder_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0), padx=0)
        self.save_all_button.pack(side=tk.LEFT, padx=(0, 5), pady=5)
        self.add_jour_frame_button.pack(side=tk.LEFT, padx=(0, 5), pady=5) # Renamed

    def on_sort_option_changed(self, event=None):
        if self._initializing or self.is_external_dragging(): return
        self.sort_grid_items_and_reflow()

    def sort_grid_items_and_reflow(self):
        if not self.grid_items: return

        sort_key_name, reverse_order = self.sort_options[self.sort_var.get()]
        def get_sort_key(grid_item_widget):
            if sort_key_name == "name": return grid_item_widget.basename.lower()
            elif sort_key_name == "date":
                ts = grid_item_widget.datetime_original_ts if grid_item_widget.datetime_original_ts is not None else grid_item_widget.file_mod_time_ts
                return ts if ts is not None else (float('-inf') if reverse_order else float('inf'))
            return grid_item_widget.basename.lower()

        self.grid_items.sort(key=get_sort_key, reverse=reverse_order)
        if self.grid_canvas and self.grid_canvas.winfo_exists():
            current_canvas_width = self.grid_canvas.winfo_width()
            if self._reflow_job: self.grid_canvas.after_cancel(self._reflow_job)
            self._reflow_job = self.grid_canvas.after(10, self._do_reflow, current_canvas_width)

    def _update_stats_label(self):
        if not hasattr(self, 'stats_label') or not self.stats_label or not self.stats_label.winfo_exists(): return
        num_grid_images = len([gi for gi in self.grid_items_dict.values() if gi and gi.is_valid])
        num_jour_images = sum(len(jf.images_data) for jf in self.jour_frames if jf and jf.frame and jf.frame.winfo_exists()) # Renamed
        self.stats_label.config(text=f"Grille: {num_grid_images} | Jours: {num_jour_images}") # Renamed "Couloirs" to "Jours"

    def _bind_scroll_events(self):
        for widget in [self.grid_canvas, self.grid_inner_frame]:
             if widget and widget.winfo_exists():
                 widget.bind("<MouseWheel>", self._on_grid_mousewheel, add='+')
                 widget.bind("<Button-4>", self._on_grid_mousewheel, add='+'); widget.bind("<Button-5>", self._on_grid_mousewheel, add='+')
        if self.jour_frames_canvas and self.jour_frames_canvas.winfo_exists(): # Renamed
            self.jour_frames_canvas.bind("<MouseWheel>", self._on_jour_frames_area_mousewheel, add='+') # Renamed
            self.jour_frames_canvas.bind("<Button-4>", self._on_jour_frames_area_mousewheel, add='+'); self.jour_frames_canvas.bind("<Button-5>", self._on_jour_frames_area_mousewheel, add='+') # Renamed

    def _bind_configure_events(self):
        if self.grid_inner_frame: self.grid_inner_frame.bind("<Configure>", self._on_inner_frame_configure, add='+')
        if self.grid_canvas: self.grid_canvas.bind("<Configure>", self._on_canvas_configure, add='+')
        if self.jour_frames_container: self.jour_frames_container.bind("<Configure>", self._on_jour_frames_container_configure, add='+') # Renamed
        if self.jour_frames_canvas: self.jour_frames_canvas.bind("<Configure>", self._on_jour_frames_canvas_configure, add='+') # Renamed

    def select_images(self):
        if self.is_external_dragging(): return False
        parent_widget = self.root if self.root and self.root.winfo_exists() else None
        try:
            paths = filedialog.askopenfilenames(parent=parent_widget, title="Sélectionnez les images",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("Tous les fichiers", "*.*")])
            if paths and isinstance(paths, (list, tuple)) and len(paths) > 0:
                self.selected_paths = list(paths)
                return True
            else:
                self.selected_paths = []; return False
        except Exception as e:
            messagebox.showerror("Erreur Sélection", f"Une erreur est survenue lors de la sélection des fichiers:\n{e}", parent=parent_widget)
            self.selected_paths = []; return False

    def filter_selected_images(self, original_import_base_dir):
        self.images_to_load = []
        if not self.selected_paths or not original_import_base_dir or original_import_base_dir == ".":
            self.images_to_load = list(self.selected_paths); return

        skipped_count = 0
        norm_original_import_base_dir = os.path.normpath(original_import_base_dir)

        for fp in self.selected_paths:
            try:
                norm_fp = os.path.normpath(fp); img_dir = os.path.dirname(norm_fp)
                dir_name = os.path.basename(img_dir)
                parent_of_img_dir = os.path.dirname(img_dir)

                is_in_subfolder_of_original_import_base = (os.path.normpath(parent_of_img_dir) == norm_original_import_base_dir)
                is_jour_folder = self.jour_folder_pattern.match(dir_name) is not None # Uses updated pattern

                if is_in_subfolder_of_original_import_base and is_jour_folder:
                    skipped_count += 1; continue
            except Exception: pass
            self.images_to_load.append(fp)

    def determine_start_index(self):
        self.next_jour_index = 0 # Renamed
        if not self.base_dir or not os.path.isdir(self.base_dir): return
        highest_ord_found = -1
        try:
            for item_name in os.listdir(self.base_dir):
                item_path = os.path.join(self.base_dir, item_name)
                if os.path.isdir(item_path):
                    match = self.jour_folder_pattern.match(item_name) # Uses updated pattern
                    if match:
                        letter = match.group(1).upper(); current_ord = ord(letter)
                        if current_ord > highest_ord_found: highest_ord_found = current_ord
        except OSError: pass
        if highest_ord_found != -1:
            self.next_jour_index = (highest_ord_found - ord('A')) + 1 # Renamed

    def load_existing_jour_frames_data(self): # Renamed
        self.existing_jour_data = {} # Renamed
        if not self.base_dir or not os.path.isdir(self.base_dir): return

        original_basename_to_path_lookup = {
            os.path.normcase(os.path.basename(p)): p for p in self.images_to_load
        }
        try:
            for item_name in os.listdir(self.base_dir): # e.g., "jour A"
                jour_folder_path = os.path.join(self.base_dir, item_name)
                if os.path.isdir(jour_folder_path):
                    match = self.jour_folder_pattern.match(item_name) # Uses updated pattern
                    if match:
                        letter = match.group(1).upper()
                        if letter not in self.existing_jour_data: self.existing_jour_data[letter] = {} # Renamed
                        try:
                            for saved_filename in os.listdir(jour_folder_path):
                                saved_filepath = os.path.join(jour_folder_path, saved_filename)
                                if os.path.isfile(saved_filepath):
                                    try:
                                        parts = saved_filename.split(FILENAME_DELIMITER, 1)
                                        if len(parts) == 2:
                                            prefix = parts[0]; encoded_part_with_ext = parts[1]
                                            saved_index = -1
                                            if len(prefix) > 1 and prefix[0].isalpha() and \
                                            prefix[0].upper() == letter and prefix[1:].isdigit():
                                                saved_index = int(prefix[1:])
                                            else: continue

                                            encoded_root, original_ext = os.path.splitext(encoded_part_with_ext)
                                            original_root = safe_decode_basename(encoded_root)
                                            original_basename = original_root + original_ext

                                            normcased_orig_basename_for_lookup = os.path.normcase(original_basename)
                                            actual_original_path_ref = original_basename_to_path_lookup.get(normcased_orig_basename_for_lookup)

                                            if actual_original_path_ref:
                                                if saved_index not in self.existing_jour_data[letter]: # Renamed
                                                    self.existing_jour_data[letter][saved_index] = { # Renamed
                                                        'display_path': saved_filepath,
                                                        'original_reference_path': actual_original_path_ref
                                                    }
                                    except Exception: pass
                        except OSError: pass
        except OSError: pass

    def load_grid_items(self):
        if not self.images_to_load: return False
        for item_widget in self.grid_items:
            if item_widget and isinstance(item_widget, tk.Widget) and item_widget.winfo_exists():
                try:
                    item_widget.destroy()
                except tk.TclError:
                    pass
        self.grid_items.clear(); self.grid_items_dict.clear()
        loading_screen = None
        try:
            if not self.grid_inner_frame or not self.grid_inner_frame.winfo_exists(): return False
            total_to_load = len(self.images_to_load)
            loading_screen = PubOrgLoadingScreen(self.root, total=total_to_load)
            count = 0; failed_files_info = []

            temp_grid_items = []
            for fp_original_ref in self.images_to_load:
                count += 1; gi = None
                try:
                    if not os.path.isfile(fp_original_ref):
                        failed_files_info.append(f"{os.path.basename(fp_original_ref)} (Not a file)")
                        if loading_screen: loading_screen.update(count)
                        continue
                    gi = GridItem(self.grid_inner_frame, fp_original_ref, self.current_thumb_size, self.grid_margin)
                    temp_grid_items.append(gi)
                    self.grid_items_dict[fp_original_ref] = gi

                    gi.click_callback = self.on_grid_item_click
                    gi.bind("<MouseWheel>", self._on_grid_mousewheel, add='+')
                    gi.bind("<Button-4>", self._on_grid_mousewheel, add='+'); gi.bind("<Button-5>", self._on_grid_mousewheel, add='+')
                    if not gi.is_valid:
                        failed_files_info.append(f"{os.path.basename(fp_original_ref)} (Load Error in GridItem)")
                except Exception as e:
                    failed_files_info.append(f"{os.path.basename(fp_original_ref)} (Widget Creation Error: {e})")
                    if gi and isinstance(gi, tk.Widget) and gi.winfo_exists():
                        try:
                            gi.destroy()
                        except tk.TclError:
                            pass
                    if fp_original_ref in self.grid_items_dict: del self.grid_items_dict[fp_original_ref]
                    if gi in temp_grid_items: temp_grid_items.remove(gi)
                finally:
                    if loading_screen: loading_screen.update(count)

            self.grid_items = temp_grid_items

            if loading_screen: loading_screen.destroy(); loading_screen = None
            if failed_files_info:
                 fail_summary = "\n".join([f"- {f}" for f in failed_files_info[:10]]) + ("\n- ..." if len(failed_files_info) > 10 else "")
                 messagebox.showwarning("Grid Loading Errors",f"{len(failed_files_info)} image(s) problématiques.\n{fail_summary}", parent=self.root if self.root.winfo_viewable() else None)

            self._update_stats_label()
            return bool(self.grid_items)
        except Exception as load_err:
             if loading_screen: loading_screen.destroy()
             messagebox.showerror("Critical Loading Error", f"Erreur critique chargement grille:\n{load_err}", parent=self.root if self.root.winfo_viewable() else None)
             return False
        finally:
             if loading_screen and hasattr(loading_screen, 'top') and loading_screen.top and loading_screen.top.winfo_exists():
                 loading_screen.destroy()


    def mark_grid_items_from_existing_data(self):
        if not self.existing_jour_data: return # Renamed
        for letter, items_in_jour in self.existing_jour_data.items(): # Renamed
            try:
                jour_idx = ord(letter) - ord('A') # Renamed
                color = JOUR_COLORS[jour_idx % len(JOUR_COLORS)] # Use JOUR_COLORS
                for saved_index, data_dict in items_in_jour.items():
                    original_ref_path = data_dict.get('original_reference_path')
                    if original_ref_path:
                        grid_item_widget = self.grid_items_dict.get(original_ref_path)
                        if grid_item_widget and grid_item_widget.winfo_exists() and grid_item_widget.is_valid:
                            label = f"{letter}{saved_index}"
                            grid_item_widget.mark_used(label, color)
            except Exception: pass

    def create_and_populate_existing_jour_frames(self): # Renamed
        if not self.existing_jour_data: return # Renamed
        sorted_letters = sorted(self.existing_jour_data.keys()) # Renamed
        for letter in sorted_letters:
            jour_idx = ord(letter) - ord('A') # Renamed
            items_data_dict = self.existing_jour_data[letter] # Renamed
            jour_frame_instance = None # Renamed
            try:
                if not self.jour_frames_container or not self.jour_frames_container.winfo_exists(): continue # Renamed
                jour_frame_instance = JourFrame(parent_frame=self.jour_frames_container, organizer=self, index=jour_idx, # Renamed class
                                             base_dir=self.base_dir, update_callback=self.update_grid_usage)
                if self.button_holder_frame and self.button_holder_frame.winfo_exists():
                     jour_frame_instance.frame.pack(fill=tk.X, pady=5, padx=5, side=tk.BOTTOM, before=self.button_holder_frame)
                else: jour_frame_instance.frame.pack(fill=tk.X, pady=5, padx=5, side=tk.BOTTOM)
                self.jour_frames.append(jour_frame_instance) # Renamed

                items_to_add_sorted = sorted(
                    [((data['display_path'], data['original_reference_path']), saved_idx)
                     for saved_idx, data in items_data_dict.items() if os.path.isfile(data['display_path'])],
                    key=lambda item_tuple: item_tuple[1]
                )
                for (display_p, original_ref_p), _ in items_to_add_sorted:
                    jour_frame_instance.insert_image_at((display_p, original_ref_p), len(jour_frame_instance.images_data))
                jour_frame_instance.reposition_all()
            except Exception as e:
                 print(f"  ERROR creating/populating JourFrame {letter}: {e}") # Renamed
                 if jour_frame_instance in self.jour_frames: self.jour_frames.remove(jour_frame_instance) # Renamed
                 if jour_frame_instance and jour_frame_instance.frame and jour_frame_instance.frame.winfo_exists():
                     try: jour_frame_instance.destroy()
                     except Exception: pass
        self.jour_frames.sort(key=lambda jf: jf.index) # Renamed
        self.root.after_idle(self._on_jour_frames_container_configure, None) # Renamed
        self._update_stats_label()

    def _zoom_in(self):
        if self._initializing or self.is_external_dragging(): return
        new_w = self.current_thumb_size[0] + self.zoom_step; new_h = self.current_thumb_size[1] + self.zoom_step
        if new_w <= self.max_thumb_size[0] and new_h <= self.max_thumb_size[1]:
            self.current_thumb_size = (new_w, new_h); self._apply_zoom()

    def _zoom_out(self):
        if self._initializing or self.is_external_dragging(): return
        new_w = self.current_thumb_size[0] - self.zoom_step; new_h = self.current_thumb_size[1] - self.zoom_step
        if new_w >= self.min_thumb_size[0] and new_h >= self.min_thumb_size[1]:
            self.current_thumb_size = (new_w, new_h); self._apply_zoom()

    def _apply_zoom(self):
        if not self.grid_items: return
        if self.zoom_label and self.zoom_label.winfo_exists(): self.zoom_label.config(text=f"{self.current_thumb_size[0]}px")
        for item_widget in self.grid_items:
            if item_widget and item_widget.winfo_exists():
                try: item_widget.update_size(self.current_thumb_size)
                except Exception: pass
        if self.grid_canvas and self.grid_canvas.winfo_exists():
             current_canvas_width = self.grid_canvas.winfo_width()
             if self._reflow_job: self.grid_canvas.after_cancel(self._reflow_job)
             self._reflow_job = self.grid_canvas.after(10, self._do_reflow, current_canvas_width)

    def _on_inner_frame_configure(self, event):
        try:
             if not self.grid_canvas or not self.grid_inner_frame or not self.grid_inner_frame_id: return
             self.grid_canvas.update_idletasks()
             bbox = self.grid_canvas.bbox(self.grid_inner_frame_id)
             if bbox: self.grid_canvas.configure(scrollregion=(bbox[0], bbox[1], max(bbox[2], self.grid_canvas.winfo_width()), bbox[3]))
             else: self.grid_canvas.configure(scrollregion=(0, 0, self.grid_canvas.winfo_width(), self.grid_canvas.winfo_height()))
        except (tk.TclError, Exception): pass

    def _on_canvas_configure(self, event):
        try:
            if self._initializing or not self.grid_canvas or not self.grid_inner_frame or not self.grid_inner_frame_id: return
            new_width = event.width
            if new_width > 1:
                self.grid_canvas.itemconfig(self.grid_inner_frame_id, width=new_width)
                if self._reflow_job: self.grid_canvas.after_cancel(self._reflow_job)
                self._reflow_job = self.grid_canvas.after(150, self._do_reflow, new_width)
        except (tk.TclError, Exception): pass

    def _do_reflow(self, canvas_width):
         try:
             if self._initializing or not self.grid_canvas or not self.grid_inner_frame: return
             self.reflow_grid(canvas_width)
         except (tk.TclError, Exception): pass
         finally: self._reflow_job = None

    def reflow_grid(self, canvas_width=None):
        try:
            if not self.grid_inner_frame or not self.grid_inner_frame.winfo_exists(): return
            if self._initializing or not self.grid_items:
                current_cols, current_rows = self.grid_inner_frame.grid_size()
                for c in range(current_cols): self.grid_inner_frame.columnconfigure(c, weight=0, minsize=0, pad=0)
                for r in range(current_rows): self.grid_inner_frame.rowconfigure(r, weight=0, minsize=0, pad=0)
                return

            if canvas_width is None or canvas_width <= 1:
                 if not self.grid_canvas or not self.grid_canvas.winfo_exists(): return
                 canvas_width = self.grid_canvas.winfo_width()
                 if canvas_width <= 1 : canvas_width = 600

            first_valid_item = next((gi for gi in self.grid_items if gi and gi.winfo_exists() and gi.is_valid), None)
            item_total_width = first_valid_item.winfo_reqwidth() if first_valid_item else self.current_thumb_size[0] + 2 * self.grid_margin + 2
            item_total_height = first_valid_item.winfo_reqheight() if first_valid_item else self.current_thumb_size[1] + 2 * self.grid_margin + 2
            if item_total_width <= 0: item_total_width = self.min_thumb_size[0] + 2*self.grid_margin + 2
            if item_total_height <= 0: item_total_height = self.min_thumb_size[1] + 2*self.grid_margin + 2

            scrollbar_width = self.grid_scrollbar.winfo_reqwidth() if self.grid_scrollbar.winfo_ismapped() else 0
            effective_canvas_width = max(1, canvas_width - scrollbar_width - 10)
            col_spacing_width = item_total_width + self.grid_margin
            cols = max(1, int(effective_canvas_width // col_spacing_width)) if col_spacing_width > 0 else 1

            prev_cols, prev_rows = self.grid_inner_frame.grid_size()
            for c_idx in range(prev_cols): self.grid_inner_frame.columnconfigure(c_idx, weight=0, minsize=0, pad=0)
            for r_idx in range(prev_rows): self.grid_inner_frame.rowconfigure(r_idx, weight=0, minsize=0, pad=0)
            for child in self.grid_inner_frame.winfo_children(): child.grid_forget()

            row_num, col_num = 0, 0
            for widget in self.grid_items:
                  if isinstance(widget, GridItem) and widget.winfo_exists():
                     widget.grid(row=row_num, column=col_num, padx=self.grid_margin//2, pady=self.grid_margin//2, sticky="nsew")
                     col_num += 1
                     if col_num >= cols: col_num = 0; row_num += 1

            num_rows_used = row_num + (1 if col_num > 0 else 0)
            for c in range(cols): self.grid_inner_frame.columnconfigure(c, weight=1, minsize=item_total_width, pad=self.grid_margin//2)
            for r in range(num_rows_used): self.grid_inner_frame.rowconfigure(r, weight=0, minsize=item_total_height, pad=self.grid_margin//2)

            self.root.after_idle(self._on_inner_frame_configure, None)
        except (tk.TclError, Exception) as e:
            print(f"Erreur dans reflow_grid: {e}")

    def _on_grid_mousewheel(self, event):
        try:
            if self._initializing or not self.grid_canvas or not self.grid_canvas.winfo_exists(): return
            delta = 0
            if sys.platform == 'darwin': delta = -1 * event.delta
            elif sys.platform == 'linux': delta = -1 if event.num == 4 else (1 if event.num == 5 else 0)
            else: delta = -1 * int(event.delta / 120)

            if delta != 0: self.grid_canvas.yview_scroll(delta, "units"); return "break"
        except (tk.TclError, Exception): pass

    def _on_jour_frames_container_configure(self, event): # Renamed
        try:
            if not self.jour_frames_canvas or not self.jour_frames_container or not self.jour_frames_container_id: return # Renamed
            self.jour_frames_canvas.update_idletasks() # Renamed
            self.jour_frames_canvas.configure(scrollregion=(0, 0, self.jour_frames_canvas.winfo_width(), self.jour_frames_container.winfo_reqheight())) # Renamed
        except (tk.TclError, Exception): pass

    def _on_jour_frames_canvas_configure(self, event): # Renamed
        try:
            if self._initializing or not self.jour_frames_canvas or not self.jour_frames_container_id or not self.jour_frames_container: return # Renamed
            if event.width > 1: self.jour_frames_canvas.itemconfig(self.jour_frames_container_id, width=event.width) # Renamed
        except (tk.TclError, Exception): pass

    def _on_jour_frames_area_mousewheel(self, event): # Renamed
        try:
            if self._initializing or not self.jour_frames_canvas or not self.jour_frames_canvas.winfo_exists(): return # Renamed
            delta = 0
            if sys.platform == 'darwin': delta = -1 * event.delta
            elif sys.platform == 'linux': delta = -1 if event.num == 4 else (1 if event.num == 5 else 0)
            else: delta = -1 * int(event.delta / 120)

            if delta != 0: self.jour_frames_canvas.yview_scroll(delta, "units"); return "break" # Renamed
        except (tk.TclError, Exception): pass

    def on_grid_item_click(self, grid_item):
        if self._initializing or self.is_external_dragging(): return
        if not grid_item or not grid_item.winfo_exists() or not hasattr(grid_item, 'file_path') or not grid_item.file_path:
            return

        original_reference_path = grid_item.file_path
        combined_usage = self.get_combined_usage_map()
        norm_original_ref_path = os.path.normcase(original_reference_path)

        usage_entry = None
        for map_orig_ref, entry_data in combined_usage.items():
            if os.path.normcase(map_orig_ref) == norm_original_ref_path:
                usage_entry = entry_data; break

        if usage_entry:
            jour_letter_str = usage_entry[3] # Renamed
            found_jour_frame = next((jf for jf in self.jour_frames if jf.letter == jour_letter_str), None) # Renamed
            if found_jour_frame: # Renamed
                if not found_jour_frame.remove_image_by_original_reference_path(original_reference_path): # Renamed
                    pass
            else:
                messagebox.showerror("Erreur Interne", f"Jour {jour_letter_str} non trouvé pour suppression.", parent=self.root) # Renamed
        else:
            if not self.current_jour_frame: # Renamed
                messagebox.showwarning("Aucun Jour Actif", "Veuillez sélectionner ou ajouter un Jour.", parent=self.root) # Renamed
                return
            file_path_tuple_to_add = (original_reference_path, original_reference_path)
            if not self.current_jour_frame.add_image(file_path_tuple_to_add): # Renamed
                pass
        self.update_grid_usage()

    def get_combined_usage_map(self):
        combined_map = dict(self.permanent_usage_map)
        for jour_frame in list(self.jour_frames): # Renamed
            try:
                 if jour_frame and jour_frame.frame and jour_frame.frame.winfo_exists(): # Renamed
                      jour_frame_usage = jour_frame.get_usage_data() # Renamed
                      combined_map.update(jour_frame_usage)
            except Exception: pass
        return combined_map

    def update_grid_usage(self):
        if self._initializing: return
        current_usage_map = self.get_combined_usage_map()
        used_orig_ref_paths_normcased = {os.path.normcase(p) for p in current_usage_map.keys()}

        for original_ref_path, grid_item_widget in self.grid_items_dict.items():
            try:
                 if grid_item_widget and grid_item_widget.winfo_exists() and grid_item_widget.is_valid:
                    norm_orig_ref_path = os.path.normcase(original_ref_path)
                    if norm_orig_ref_path in used_orig_ref_paths_normcased:
                        usage_info = next((info for map_path, info in current_usage_map.items() if os.path.normcase(map_path) == norm_orig_ref_path), None)
                        if usage_info: grid_item_widget.mark_used(usage_info[0], usage_info[1])
                        else: grid_item_widget.mark_unused()
                    else: grid_item_widget.mark_unused()
            except (tk.TclError, Exception): pass
        self._update_stats_label()

    def notify_jour_frame_saved(self, jour_frame, saved_folder, is_empty): # Renamed
        if self.programmation_page:
            target_date = datetime.date.today() # Example: always schedule for today when saved
                                                # In a real app, you'd likely have a date picker for the JourFrame or global setting
            if is_empty:
                self.programmation_page.remove_publication_for_date(target_date, jour_frame.letter)
            else:
                label = f"Jour {jour_frame.letter}" # Renamed "Pub" to "Jour"
                self.programmation_page.add_or_update_publication_for_date(
                    target_date, jour_frame.letter, label
                )

    def add_jour_frame(self): # Renamed
        is_initial_default_call = (self._initializing and not self.jour_frames and not self.existing_jour_data) # Renamed
        if self._initializing and not is_initial_default_call: return
        if self.is_external_dragging(): return

        new_index = self.next_jour_index # Renamed
        if new_index >= 26:
             messagebox.showwarning("Limite Atteinte", "Maximum de Jours (A-Z) atteint.", parent=self.root); return # Renamed
        new_letter = chr(ord('A') + new_index)

        target_date_for_new_jour = datetime.date.today() # Renamed
        if self.programmation_page:
            scheduled_letters_today = self.programmation_page.get_scheduled_letters_for_date(target_date_for_new_jour)
            if new_letter in scheduled_letters_today:
                if not messagebox.askyesno("Conflit de Programmation",
                                           f"La publication pour le Jour '{new_letter}' est déjà programmée pour aujourd'hui ({target_date_for_new_jour.strftime('%d/%m/%Y')}).\n"
                                           f"Voulez-vous quand même créer ce Jour ? (Il écrasera l'entrée existante dans le calendrier lors de sa sauvegarde)",
                                           parent=self.root):
                    return

        new_jour_frame = None # Renamed
        try:
            if not self.jour_frames_container or not self.jour_frames_container.winfo_exists(): # Renamed
                 error_msg = "Erreur interne: Conteneur des Jours absent." # Renamed
                 if is_initial_default_call: self.exit_app(error_msg); return
                 else: messagebox.showerror("Erreur Interne", error_msg, parent=self.root); return

            new_jour_frame = JourFrame(self.jour_frames_container, self, new_index, self.base_dir, self.update_grid_usage) # Renamed
        except Exception as e:
             error_msg = f"Erreur création Jour {new_letter}:\n{e}" # Renamed
             if is_initial_default_call: self.exit_app(error_msg)
             else: messagebox.showerror("Erreur Création Jour", error_msg, parent=self.root) # Renamed
             if new_jour_frame and new_jour_frame.frame and new_jour_frame.frame.winfo_exists(): # Renamed
                 try: new_jour_frame.destroy() # Renamed
                 except Exception: pass
             return
        try:
             pack_before = self.button_holder_frame if self.button_holder_frame and self.button_holder_frame.winfo_exists() else None
             new_jour_frame.frame.pack(fill=tk.X, pady=5, padx=5, side=tk.BOTTOM, before=pack_before) # Renamed
        except tk.TclError:
             try: new_jour_frame.frame.pack(fill=tk.X, pady=5, padx=5) # Renamed
             except Exception:
                 error_msg = f"Erreur UI: Impossible d'afficher le Jour {new_letter}." # Renamed
                 if is_initial_default_call: self.exit_app(error_msg)
                 else: messagebox.showerror("Erreur UI", error_msg, parent=self.root)
                 if new_jour_frame in self.jour_frames: self.jour_frames.remove(new_jour_frame) # Renamed
                 if new_jour_frame and hasattr(new_jour_frame, 'destroy'): # Renamed
                     try: new_jour_frame.destroy() # Renamed
                     except Exception: pass
                 return
        self.jour_frames.append(new_jour_frame); self.jour_frames.sort(key=lambda jf: jf.index) # Renamed
        if not is_initial_default_call or not self.current_jour_frame : self.set_current_jour_frame(new_jour_frame) # Renamed
        self.next_jour_index += 1 # Renamed
        self.root.after_idle(self._on_jour_frames_container_configure, None) # Renamed
        self.root.after_idle(self.update_grid_usage)

    def close_jour_frame(self, jour_frame_to_close): # Renamed
        if self._initializing or self.is_external_dragging() or jour_frame_to_close not in self.jour_frames: return # Renamed
        try:
             self.permanent_usage_map.update(jour_frame_to_close.get_usage_data())
             original_index = self.jour_frames.index(jour_frame_to_close) if jour_frame_to_close in self.jour_frames else -1 # Renamed
             self.jour_frames.remove(jour_frame_to_close) # Renamed
             new_current = self.current_jour_frame # Renamed
             if self.current_jour_frame == jour_frame_to_close: # Renamed
                 if self.jour_frames: # Renamed
                     new_idx = max(0, min(original_index if original_index != -1 else 0, len(self.jour_frames)-1)) # Renamed
                     new_current = self.jour_frames[new_idx] if 0 <= new_idx < len(self.jour_frames) else self.jour_frames[0] # Renamed
                 else: new_current = None

             if self.programmation_page:
                 self.programmation_page.remove_publication_for_date(datetime.date.today(), jour_frame_to_close.letter)

             jour_frame_to_close.destroy()
             self.set_current_jour_frame(new_current) # Renamed
             self.root.after_idle(self._on_jour_frames_container_configure, None) # Renamed
             self.root.after_idle(self.update_grid_usage)
        except Exception:
             if jour_frame_to_close in self.jour_frames: self.jour_frames.remove(jour_frame_to_close) # Renamed
             self.update_grid_usage()
             if not self.current_jour_frame or not (hasattr(self.current_jour_frame, 'frame') and self.current_jour_frame.frame and self.current_jour_frame.frame.winfo_exists()): # Renamed
                 self.set_current_jour_frame(self.jour_frames[-1] if self.jour_frames else None) # Renamed
             self.root.after_idle(self._on_jour_frames_container_configure, None) # Renamed

    def set_current_jour_frame(self, jour_frame): # Renamed
        if self.is_external_dragging() or self.current_jour_frame == jour_frame: return # Renamed
        if self.current_jour_frame: # Renamed
            try:
                if hasattr(self.current_jour_frame, 'frame') and self.current_jour_frame.frame and self.current_jour_frame.frame.winfo_exists(): # Renamed
                     default_bg = self.current_jour_frame.frame.master.cget('bg') # Renamed
                     self.current_jour_frame.frame.config(bg=default_bg, relief="groove", highlightthickness=0) # Renamed
                     if hasattr(self.current_jour_frame, 'label') and self.current_jour_frame.label and self.current_jour_frame.label.winfo_exists(): # Renamed
                         self.current_jour_frame.label.config(bg="lightgray") # Renamed
            except (tk.TclError, AttributeError, Exception): pass

        self.current_jour_frame = jour_frame # Renamed
        if self.current_jour_frame: # Renamed
             try:
                  if hasattr(self.current_jour_frame, 'frame') and self.current_jour_frame.frame and self.current_jour_frame.frame.winfo_exists(): # Renamed
                       select_color = "lightblue"
                       self.current_jour_frame.frame.config(bg=select_color, relief="sunken", highlightbackground=select_color, highlightcolor=select_color, highlightthickness=2) # Renamed
                       if hasattr(self.current_jour_frame, 'label') and self.current_jour_frame.label and self.current_jour_frame.label.winfo_exists(): # Renamed
                           self.current_jour_frame.label.config(bg=select_color) # Renamed
                  else: self.current_jour_frame = None # Renamed
             except (tk.TclError, AttributeError, Exception): self.current_jour_frame = None # Renamed

    def save_all_jour_frames(self): # Renamed
        if self._initializing or self.is_external_dragging(): return
        if not self.jour_frames: # Renamed
             messagebox.showinfo("Tout Enregistrer", "Aucun Jour actif à enregistrer.", parent=self.root); return # Renamed
        saved_count = 0; failed_letters = []; empty_count = 0
        original_button_state = tk.NORMAL
        if self.save_all_button and self.save_all_button.winfo_exists():
            original_button_state = self.save_all_button.cget('state')
            self.save_all_button.config(state=tk.DISABLED); self.root.update_idletasks()

        for jour_frame in list(self.jour_frames): # Renamed
            try:
                if jour_frame and jour_frame.frame and jour_frame.frame.winfo_exists(): # Renamed
                    if jour_frame.save(): # Renamed
                        if jour_frame.images_data: saved_count += 1 # Renamed
                        else: empty_count += 1
                    else: failed_letters.append(jour_frame.letter) # Renamed
                else: failed_letters.append(getattr(jour_frame, 'letter', '??')) # Renamed
            except Exception: failed_letters.append(getattr(jour_frame, 'letter', '??')) # Renamed

        if self.save_all_button and self.save_all_button.winfo_exists():
            self.save_all_button.config(state=original_button_state)

        msg_parts = []
        if not failed_letters: msg_parts.append(f"Enregistrement de tous les Jours terminé.") # Renamed
        else: msg_parts.append(f"Enregistrement terminé AVEC ERREURS.")
        if saved_count > 0: msg_parts.append(f"{saved_count} Jour(s) non vide(s) enregistré(s).") # Renamed
        if empty_count > 0: msg_parts.append(f"{empty_count} Jour(s) vide(s) traité(s).") # Renamed
        if failed_letters: msg_parts.append(f"Erreurs pour Jour(s) : {', '.join(sorted(list(set(failed_letters))))}.") # Renamed
        messagebox.showinfo("Tout Enregistrer - Rapport", "\n".join(msg_parts), parent=self.root)
        self._update_stats_label()

    # --- External Drag & Drop (Inter-JourFrame) Methods ---
    def is_external_dragging(self):
        return self.external_drag_window is not None and self.external_drag_window.winfo_exists()

    def _setup_external_drag_bindings(self):
        if self._initializing or self._external_bindings_active: return
        try:
            if self.root and self.root.winfo_exists() and self.root.winfo_viewable():
                self.root.bind("<Motion>", self.update_external_drag_position, add='+')
                self.root.bind("<ButtonRelease-1>", self.on_external_drag_release, add='+')
                try: self.root.grab_set()
                except tk.TclError: pass
                self._external_bindings_active = True
        except tk.TclError: self._remove_external_drag_bindings()

    def _remove_external_drag_bindings(self):
        if self._external_bindings_active:
            try:
                if self.root and self.root.winfo_exists():
                    try: self.root.grab_release()
                    except tk.TclError: pass
                    self.root.unbind("<Motion>"); self.root.unbind("<ButtonRelease-1>")
                self._external_bindings_active = False
            except (tk.TclError, Exception): pass

    def start_external_drag(self, source_jour_frame, source_item_id, file_path_tuple, photo_image, event): # Renamed
        if self._initializing or self.is_external_dragging():
            if self.is_external_dragging(): self.cancel_external_drag(reposition_source=True)
            return
        self.external_drag_path_tuple = file_path_tuple
        self.external_drag_photo = photo_image
        self.external_drag_source_jour_frame = source_jour_frame # Renamed
        self.external_drag_source_item_id = source_item_id
        try:
            if not self.root or not self.root.winfo_exists(): return
            self.external_drag_window = tk.Toplevel(self.root)
            self.external_drag_window.overrideredirect(True); self.external_drag_window.attributes("-topmost", True)
            try: self.external_drag_window.attributes("-alpha", 0.75)
            except tk.TclError: pass
            tk.Label(self.external_drag_window, image=self.external_drag_photo, bg='white', relief='solid', bd=1).pack()
            self.update_external_drag_position(event); self._setup_external_drag_bindings()
        except Exception: self.cancel_external_drag(reposition_source=True)

    def update_external_drag_position(self, event):
        if self._initializing or not self.is_external_dragging():
            if self._external_bindings_active: self.cancel_external_drag()
            return
        try:
            if not self.root or not self.external_drag_window or not self.external_drag_window.winfo_exists():
                self.cancel_external_drag(); return
            mouse_x, mouse_y = event.x_root, event.y_root
            self.external_drag_window.update_idletasks()
            win_w=self.external_drag_window.winfo_width(); win_h=self.external_drag_window.winfo_height()
            screen_w=self.root.winfo_screenwidth(); screen_h=self.root.winfo_screenheight()
            new_x=max(0, min(mouse_x + 15, screen_w - win_w)); new_y=max(0, min(mouse_y + 10, screen_h - win_h))
            self.external_drag_window.geometry(f"+{new_x}+{new_y}")

            try:
                default_bg = self.root.cget('bg')
            except tk.TclError:
                default_bg = "SystemButtonFace" if sys.platform == "win32" else "#D9D9D9"

            for jour_frame_widget in list(self.jour_frames): # Renamed
                try:
                    if not jour_frame_widget or not jour_frame_widget.frame or not jour_frame_widget.canvas or not jour_frame_widget.canvas.winfo_exists(): continue # Renamed
                    c_abs_x = jour_frame_widget.canvas.winfo_rootx(); c_abs_y = jour_frame_widget.canvas.winfo_rooty() # Renamed
                    c_width = jour_frame_widget.canvas.winfo_width(); c_height = jour_frame_widget.canvas.winfo_height() # Renamed
                    is_over_canvas = (c_width > 1 and c_height > 1 and \
                                      c_abs_x <= mouse_x < c_abs_x + c_width and \
                                      c_abs_y <= mouse_y < c_abs_y + c_height)
                    is_current = (jour_frame_widget == self.current_jour_frame); is_source = (jour_frame_widget == self.external_drag_source_jour_frame) # Renamed
                    frame_bg_style, relief_style, hl_thick_style, hl_color_style, lbl_bg_style = default_bg, "groove", 0, default_bg, "lightgray"
                    if is_over_canvas and not is_source:
                        frame_bg_style, relief_style, hl_thick_style, hl_color_style, lbl_bg_style = "lightgreen", "raised", 2, "darkgreen", "lightgreen"
                    elif is_current and not is_source:
                        frame_bg_style, relief_style, hl_thick_style, hl_color_style, lbl_bg_style = "lightblue", "sunken", 2, "lightblue", "lightblue"
                    elif is_source and is_over_canvas:
                        pass
                    elif is_source:
                        pass

                    if jour_frame_widget.frame.winfo_exists(): # Renamed
                        jour_frame_widget.frame.config(relief=relief_style, highlightbackground=hl_color_style, highlightcolor=hl_color_style, highlightthickness=hl_thick_style, bg=frame_bg_style) # Renamed
                        if hasattr(jour_frame_widget, 'label') and jour_frame_widget.label and jour_frame_widget.label.winfo_exists(): jour_frame_widget.label.config(bg=lbl_bg_style) # Renamed
                except (tk.TclError, AttributeError, Exception): pass
        except (tk.TclError, Exception): self.cancel_external_drag(reposition_source=True)

    def on_external_drag_release(self, event):
        if self._initializing or not self.is_external_dragging():
            if self._external_bindings_active: self._remove_external_drag_bindings()
            return "break"

        dragged_path_tuple = self.external_drag_path_tuple
        src_jour_frame = self.external_drag_source_jour_frame # Renamed

        self.cancel_external_drag(reposition_source=False)

        if not dragged_path_tuple or not src_jour_frame: # Renamed
             if src_jour_frame and hasattr(src_jour_frame,'canvas') and src_jour_frame.canvas and src_jour_frame.canvas.winfo_exists(): # Renamed
                 try: src_jour_frame.reposition_all() # Renamed
                 except Exception: pass
             return "break"

        target_jour_frame = None; drop_canvas_x = None # Renamed
        mouse_x, mouse_y = event.x_root, event.y_root
        for jour_frame_widget in list(self.jour_frames): # Renamed
            try:
                 if not jour_frame_widget or not jour_frame_widget.canvas or not jour_frame_widget.canvas.winfo_exists(): continue # Renamed
                 c_abs_x=jour_frame_widget.canvas.winfo_rootx(); c_abs_y=jour_frame_widget.canvas.winfo_rooty() # Renamed
                 c_width=jour_frame_widget.canvas.winfo_width(); c_height=jour_frame_widget.canvas.winfo_height() # Renamed
                 if (c_width > 1 and c_height > 1 and c_abs_x <= mouse_x < c_abs_x + c_width and c_abs_y <= mouse_y < c_abs_y + c_height):
                     target_jour_frame = jour_frame_widget # Renamed
                     drop_canvas_x = target_jour_frame.canvas.canvasx(mouse_x - c_abs_x); break # Renamed
            except Exception: continue

        update_grid_needed = False
        dp_dragged, orp_dragged = dragged_path_tuple
        item_successfully_moved_or_removed_from_source = False

        if target_jour_frame and target_jour_frame != src_jour_frame: # Renamed
            if target_jour_frame.insert_image_at(dragged_path_tuple, target_jour_frame._calculate_insert_index(drop_canvas_x)): # Renamed
                update_grid_needed = True
                if src_jour_frame.remove_image_by_display_path(dp_dragged): # Renamed
                    item_successfully_moved_or_removed_from_source = True
                else:
                    if src_jour_frame and src_jour_frame.canvas and src_jour_frame.canvas.winfo_exists(): # Renamed
                        src_jour_frame.rebuild_and_reposition() # Renamed
            else:
                if src_jour_frame and src_jour_frame.canvas and src_jour_frame.canvas.winfo_exists(): # Renamed
                    src_jour_frame.reposition_all() # Renamed
        elif target_jour_frame == src_jour_frame: # Renamed
            src_jour_frame.reposition_all() # Renamed
            item_successfully_moved_or_removed_from_source = True
        else:
            if src_jour_frame.remove_image_by_display_path(dp_dragged): # Renamed
                item_successfully_moved_or_removed_from_source = True
                update_grid_needed = True
            else:
                if src_jour_frame and src_jour_frame.canvas and src_jour_frame.canvas.winfo_exists(): # Renamed
                     src_jour_frame.rebuild_and_reposition() # Renamed
                update_grid_needed = True

        if not item_successfully_moved_or_removed_from_source:
            if src_jour_frame and src_jour_frame.canvas and src_jour_frame.canvas.winfo_exists(): # Renamed
                src_jour_frame.reposition_all() # Renamed

        if update_grid_needed: self.root.after_idle(self.update_grid_usage)
        return "break"


    def cancel_external_drag(self, reposition_source=True):
        drag_was_active = self.is_external_dragging() or self._external_bindings_active
        if not drag_was_active: return
        source_jour_frame_to_reset = self.external_drag_source_jour_frame # Renamed
        if self.external_drag_window:
            try:
                if self.external_drag_window.winfo_exists(): self.external_drag_window.destroy()
            except Exception: pass
            finally: self.external_drag_window = None
        self._remove_external_drag_bindings()
        self.external_drag_photo = None; self.external_drag_path_tuple = None
        self.external_drag_source_jour_frame = None; self.external_drag_source_item_id = None # Renamed

        try:
            default_bg = self.root.cget('bg')
        except tk.TclError:
            default_bg = "SystemButtonFace" if sys.platform == "win32" else "#D9D9D9"

        for jour_frame_widget in list(self.jour_frames): # Renamed
             try:
                  if jour_frame_widget and jour_frame_widget.frame and jour_frame_widget.frame.winfo_exists(): # Renamed
                      is_current = (jour_frame_widget == self.current_jour_frame) # Renamed
                      relief, hl_thick, hl_color, frame_bg, lbl_bg = \
                          ("sunken", 2, "lightblue", "lightblue", "lightblue") if is_current \
                          else ("groove", 0, default_bg, default_bg, "lightgray")
                      jour_frame_widget.frame.config(relief=relief, highlightthickness=hl_thick, highlightbackground=hl_color, highlightcolor=hl_color, bg=frame_bg) # Renamed
                      if hasattr(jour_frame_widget, 'label') and jour_frame_widget.label and jour_frame_widget.label.winfo_exists(): jour_frame_widget.label.config(bg=lbl_bg) # Renamed
             except (tk.TclError, AttributeError, Exception): pass

        if reposition_source and source_jour_frame_to_reset: # Renamed
             try:
                  if source_jour_frame_to_reset.canvas and source_jour_frame_to_reset.canvas.winfo_exists(): # Renamed
                       source_jour_frame_to_reset.cancel_internal_drag(reposition=False) # Renamed
                       source_jour_frame_to_reset.reposition_all() # Renamed
             except Exception: pass

    def safe_destroy(self):
        self._initializing = True
        if self.is_external_dragging(): self.cancel_external_drag(reposition_source=False)
        if self.root and self.root.winfo_exists():
            try:
                if self._reflow_job: self.root.after_cancel(self._reflow_job); self._reflow_job = None
            except tk.TclError: pass
        if self.jour_frames: # Renamed
            for jour_frame_widget in list(self.jour_frames): # Renamed
                try:
                    if jour_frame_widget: jour_frame_widget.destroy() # Renamed
                except Exception: pass
            self.jour_frames.clear() # Renamed
        self.grid_items_dict.clear(); self.grid_items.clear()
        if self.root and self.root.winfo_exists():
             try: self.root.destroy()
             except tk.TclError: pass
             finally: self.root = None

    def on_close_window(self):
        self.safe_destroy()

# --- ImageCropperPopup ---
PREVIEW_WIDTH = 200; PREVIEW_HEIGHT = 250; PREVIEW_GAP = 10

class CropperLoadingScreen:
    def __init__(self, parent_toplevel):
        self.root = tk.Toplevel(parent_toplevel)
        self.root.title("Chargement Cropper...")
        self.root.geometry("400x150"); self.root.resizable(False, False); self.root.config(bg="white")
        self.root.grab_set(); self.root.protocol("WM_DELETE_WINDOW", lambda: None); self.center_window(parent_toplevel)
        self.message_label = tk.Label(self.root, text="Préparation des images...", font=("Arial", 12), bg="white")
        self.message_label.pack(pady=20)
        style = ttk.Style(); style.theme_use('clam')
        style.configure("white.Horizontal.TProgressbar", troughcolor='light gray', background='dodger blue', bordercolor="white", lightcolor='dodger blue', darkcolor='dodger blue')
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=350, mode="determinate", style="white.Horizontal.TProgressbar")
        self.progress.pack(pady=10)
        self.detail_label = tk.Label(self.root, text="", bg="white"); self.detail_label.pack(pady=5)
        self.root.lift(); self.root.attributes("-topmost", True)

    def center_window(self, parent):
        self.root.update_idletasks(); width = self.root.winfo_width(); height = self.root.winfo_height()
        if parent and parent.winfo_exists() and parent.winfo_viewable():
            px = parent.winfo_rootx(); py = parent.winfo_rooty(); pw = parent.winfo_width(); ph = parent.winfo_height()
            x = px + (pw // 2) - (width // 2); y = py + (ph // 2) - (height // 2)
        else:
            screen_width = self.root.winfo_screenwidth(); screen_height = self.root.winfo_screenheight()
            x = (screen_width // 2) - (width // 2); y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def update_progress(self, value, maximum, message="", detail=""):
        if not self.root or not self.root.winfo_exists(): return
        try:
            self.progress["value"] = (value / maximum) * 100 if maximum > 0 else 0
            if message: self.message_label.config(text=message)
            if detail: self.detail_label.config(text=detail)
            self.root.update()
        except tk.TclError: pass

    def destroy(self):
        if self.root and self.root.winfo_exists():
            try: self.root.grab_release(); self.root.destroy()
            except tk.TclError: pass
        self.root = None

class ImageCropperPopup(tk.Toplevel):
    def __init__(self, parent, image_paths_to_load, target_base_save_dir):
        super().__init__(parent)
        self.transient(parent); self.grab_set()
        self.title("Outil de Recadrage et Adaptation d'Images"); self.config(bg="white")
        try: self.state('zoomed')
        except tk.TclError: self.geometry("1200x800")

        self.image_paths = list(image_paths_to_load)
        self.target_base_save_dir = target_base_save_dir
        self.modified_paths_map = {}

        self.current_image_index = -1
        self.original_image = None; self.processed_image = None
        self.display_image_pil = None; self.display_image_tk = None
        self.flipped = False; self.save_mode = "crop"; self.ignore_save = False
        self.canvas = None; self.image_on_canvas = None
        self.image_area = (0, 0, 0, 0); self.image_ratio = 1.0
        self.crop_rect = None; self.split_line = None; self.handles = {}
        self.handle_size = 8; self.canvas_border_rect_id = None
        self.drag_data = {"x": 0, "y": 0, "item": None, "type": None}
        self.aspect_ratios = {
            "4:5 (vertical)": (4, 5), "1:1 (carré)": (1, 1),
            "16:9 (paysage)": (16, 9), "3:2 (paysage)": (3, 2),
            "8:5 (horizontal)": (8, 5), "Libre": None
        }
        self.current_aspect_ratio = "4:5 (vertical)"
        self.show_split_line = True
        self.preview_frame = None; self.preview_label_left = None; self.preview_label_right = None
        self.preview_photo_left = None; self.preview_photo_right = None
        self.preview_bg_color = "white"
        self._resize_job = None
        self.loading_screen_cropper = None

        self.protocol("WM_DELETE_WINDOW", self._on_close_window_button)
        self.create_widgets()

        if self.image_paths:
            self.loading_screen_cropper = CropperLoadingScreen(self)
            self.loading_screen_cropper.update_progress(0, len(self.image_paths), "Chargement des images pour recadrage...", f"{len(self.image_paths)} images à préparer.")
            self.after(100, self.load_first_image_after_delay)
        else:
            self.info_label.config(text="Aucune image à recadrer.")
            self.update_preview()

    def _on_close_window_button(self):
        if self.current_image_index >= 0 and self.current_image_index < len(self.image_paths) and not self.ignore_save:
            self.apply_and_save_current_image()
        self.grab_release()
        self.destroy()

    def load_first_image_after_delay(self):
        if self.loading_screen_cropper:
            self.loading_screen_cropper.destroy(); self.loading_screen_cropper = None
        self.current_image_index = -1
        self.next_image(skip_save=True)

    def create_widgets(self):
        main_frame = tk.Frame(self, bg="white"); main_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas_frame = tk.Frame(main_frame, bg="white", relief="sunken", borderwidth=1)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        self.canvas = tk.Canvas(self.canvas_frame, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.preview_frame = tk.Frame(self.canvas, bg=self.preview_bg_color, relief="ridge", borderwidth=1)
        preview_frame_width = PREVIEW_WIDTH + 4; preview_frame_height = PREVIEW_HEIGHT + 4
        self.preview_frame.place(x=10, y=10, width=preview_frame_width, height=preview_frame_height)
        self.preview_frame.pack_propagate(False)
        self.preview_label_left = tk.Label(self.preview_frame, bg=self.preview_bg_color)
        self.preview_label_right = tk.Label(self.preview_frame, bg=self.preview_bg_color)

        control_frame = tk.Frame(main_frame, padx=10, bg="white")
        control_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 10))
        action_button_frame = tk.Frame(control_frame, bg="white")
        action_button_frame.pack(fill=tk.X, pady=(0, 5))
        btn_style = {"bg": "#E1E1E1", "activebackground": "#C0C0C0", "relief": "raised", "borderwidth": 1, "padx": 5, "pady": 2, "font": ("Arial", 9)}

        prev_btn = tk.Button(action_button_frame, text="◀ Précédente", command=self.prev_image, width=12, **btn_style)
        prev_btn.pack(side=tk.LEFT, padx=(0, 5))
        next_btn = tk.Button(action_button_frame, text="Suivante ▶", command=self.next_image, width=12, **btn_style)
        next_btn.pack(side=tk.LEFT, padx=(0, 15))
        apply_and_next_btn = tk.Button(action_button_frame, text="Appliquer & Suivante", command=lambda: self.next_image(skip_save=False), **btn_style)
        apply_and_next_btn.pack(side=tk.LEFT, padx=(0,5))
        flip_btn = tk.Button(action_button_frame, text="Retourner H", command=self.toggle_flip, **btn_style)
        flip_btn.pack(side=tk.LEFT, padx=(0, 5))
        split_line_btn = tk.Button(action_button_frame, text="Ligne Split", command=self.toggle_split_line, **btn_style)
        split_line_btn.pack(side=tk.LEFT, padx=(0, 5))
        white_bars_btn = tk.Button(action_button_frame, text="Barres Blanches", command=self.add_white_bars, **btn_style)
        white_bars_btn.pack(side=tk.LEFT, padx=(0, 15))
        ignore_btn = tk.Button(action_button_frame, text="Ignorer & Suivante", command=self.ignore_image, **btn_style)
        ignore_btn.pack(side=tk.LEFT, padx=(0, 5))
        finish_btn = tk.Button(action_button_frame, text="Terminer et Appliquer", command=self.finish_and_apply, **btn_style)
        finish_btn.pack(side=tk.RIGHT, padx=(10,0))

        ratio_frame = tk.Frame(action_button_frame, bg="white")
        ratio_frame.pack(side=tk.RIGHT, padx=(10, 0))
        tk.Label(ratio_frame, text="Format Recadrage:", bg="white", font=("Arial", 9)).pack(side=tk.LEFT)
        self.ratio_var = tk.StringVar(value=self.current_aspect_ratio)
        combo_style = ttk.Style(); combo_style.map('TCombobox', fieldbackground=[('readonly','white')], selectbackground=[('readonly', 'white')], selectforeground=[('readonly', 'black')])
        self.ratio_menu = ttk.Combobox(ratio_frame, textvariable=self.ratio_var, values=list(self.aspect_ratios.keys()), width=15, state="readonly", style='TCombobox')
        self.ratio_menu.pack(side=tk.LEFT, padx=(5, 0)); self.ratio_menu.bind("<<ComboboxSelected>>", self.on_ratio_changed)

        self.info_label = tk.Label(control_frame, text="Traitement des images...", anchor=tk.W, justify=tk.LEFT, bg="white", font=("Arial", 9))
        self.info_label.pack(fill=tk.X, side=tk.BOTTOM)

        self.canvas.bind("<ButtonPress-1>", self.on_press); self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release); self.canvas.bind("<Configure>", self.on_canvas_resize)

        self.bind_all("<KeyPress-Left>", self._handle_cropper_keypress)
        self.bind_all("<KeyPress-Right>", self._handle_cropper_keypress)
        self.bind_all("<Control-KeyPress-Right>", self._handle_cropper_keypress)

    def _handle_cropper_keypress(self, event):
        if self.focus_get() is None and not any(w.focus_get() for w in self.winfo_children() if isinstance(w, (tk.Button, ttk.Combobox))):
             if self.grab_status() is None:
                return

        if event.keysym == "Left":
            self.prev_image()
            return "break"
        elif event.keysym == "Right":
            if event.state & 0x4:
                self.next_image(skip_save=True)
            else:
                self.next_image(skip_save=False)
            return "break"


    def finish_and_apply(self):
        if self.current_image_index >= 0 and self.current_image_index < len(self.image_paths) and not self.ignore_save:
            self.apply_and_save_current_image()
        self.grab_release()
        self.destroy()

    def load_current_image(self):
        if not (0 <= self.current_image_index < len(self.image_paths)):
            self.info_label.config(text="Toutes les images traitées ou aucune image chargée.")
            self.original_image = None; self.processed_image = None; self.display_image_pil = None
            if self.canvas: self.canvas.delete("all"); self.clear_crop_rect(); self.update_preview()
            self.remove_canvas_border(); return

        self.original_image = None; self.processed_image = None; self.display_image_pil = None
        self.flipped = False; self.save_mode = "crop"; self.ratio_menu.config(state="readonly")
        self.remove_canvas_border()

        file_path = self.image_paths[self.current_image_index]
        try:
            img = Image.open(file_path); img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'RGBA'): img = img.convert('RGB')
            self.original_image = img; self.display_image_pil = self.original_image

            self.image_orientation = 'h' if self.original_image.width > self.original_image.height else 'v'
            default_ratio = "8:5 (horizontal)" if self.image_orientation == 'h' else "4:5 (vertical)"
            c_is_land = self.current_aspect_ratio in ["16:9 (paysage)", "3:2 (paysage)", "8:5 (horizontal)"]
            c_is_port = self.current_aspect_ratio in ["4:5 (vertical)"]
            if (self.image_orientation == 'h' and c_is_port) or \
               (self.image_orientation == 'v' and c_is_land) or \
               self.current_aspect_ratio == "Libre" or not self.current_aspect_ratio:
                 self.current_aspect_ratio = default_ratio
            self.ratio_var.set(self.current_aspect_ratio)

            self.after(10, self._display_and_crop_initial)
        except Exception as e:
            print(f"ERREUR (Cropper) chargement image {os.path.basename(file_path)}: {e}")
            self.info_label.config(text=f"Erreur chargement {os.path.basename(file_path)}: {e}")
            self.original_image = None; self.processed_image = None; self.display_image_pil = None
            if self.canvas: self.canvas.delete("all"); self.clear_crop_rect(); self.update_preview()
            self.after(1500, lambda: self.next_image(skip_save=True))

    def _display_and_crop_initial(self):
         if not self.display_image_pil: return
         self.update_canvas()
         if self.save_mode == "crop":
             self.create_initial_crop_rect(); self.raise_crop_elements()
         else: self.clear_crop_rect()
         self.update_preview()
         self.info_label.config(text=f"Image {self.current_image_index + 1}/{len(self.image_paths)}: {os.path.basename(self.image_paths[self.current_image_index])}")

    def update_canvas(self, image_to_display=None):
        source_image = image_to_display if image_to_display else self.display_image_pil
        if self.canvas: self.canvas.delete("all")
        self.image_on_canvas = None; self.canvas_border_rect_id = None

        if not source_image:
            self.display_image_pil = None; self.display_image_tk = None
            self.image_area = (0, 0, 0, 0); self.clear_crop_rect(); self.update_preview(); return

        if not self.canvas: return

        canvas_width = self.canvas.winfo_width(); canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
             self.after(50, lambda: self.update_canvas(image_to_display)); return

        try:
            img_width, img_height = source_image.size
            if img_width <= 0 or img_height <= 0: return

            width_ratio = canvas_width / img_width; height_ratio = canvas_height / img_height
            self.image_ratio = min(width_ratio, height_ratio)
            new_width = int(img_width * self.image_ratio); new_height = int(img_height * self.image_ratio)
            if new_width <= 0 or new_height <= 0: return

            resized_img_pil = source_image.resize((new_width, new_height), CROPPER_RESIZE_FILTER)
            self.display_image_tk = ImageTk.PhotoImage(resized_img_pil)

            x_offset = (canvas_width - new_width) // 2; y_offset = (canvas_height - new_height) // 2
            self.image_on_canvas = self.canvas.create_image(x_offset, y_offset, anchor=tk.NW, image=self.display_image_tk, tags="image")
            self.image_area = (x_offset, y_offset, x_offset + new_width, y_offset + new_height)

            if self.save_mode == "white_bars":
                ix1, iy1, ix2, iy2 = self.image_area
                if ix2 > ix1 and iy2 > iy1:
                    self.canvas_border_rect_id = self.canvas.create_rectangle(ix1, iy1, ix2 -1, iy2 -1, outline="black", width=1, tags="canvas_border")

            if self.preview_frame:
                 self.preview_frame.lift()
                 preview_frame_width = PREVIEW_WIDTH + 4; preview_frame_height = PREVIEW_HEIGHT + 4
                 self.preview_frame.place(x=10, y=10, width=preview_frame_width, height=preview_frame_height)
        except Exception as e:
            print(f"Error in update_canvas (Cropper): {e}")
            self.display_image_tk = None; self.image_on_canvas = None; self.image_area = (0,0,0,0); self.update_preview()

    def remove_canvas_border(self):
        if self.canvas_border_rect_id and self.canvas:
            try: self.canvas.delete(self.canvas_border_rect_id)
            except tk.TclError: pass
            self.canvas_border_rect_id = None

    def on_canvas_resize(self, event=None):
        if self._resize_job: self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._perform_resize)

    def _perform_resize(self):
        self._resize_job = None
        if not self.winfo_exists() or not self.display_image_pil: return

        relative_crop = None
        if self.save_mode == "crop": relative_crop = self.get_relative_crop_coords()

        self.update_canvas()

        if self.save_mode == "crop":
            if relative_crop: self.restore_crop_rect_from_relative(relative_crop)
            else: self.create_initial_crop_rect()
            self.raise_crop_elements()
        else: self.clear_crop_rect()
        self.update_preview()

    def create_crop_rect(self, x1, y1, x2, y2):
        if self.save_mode != "crop" or not self.canvas: self.clear_crop_rect(); return

        x1_ord, x2_ord = min(x1, x2), max(x1, x2); y1_ord, y2_ord = min(y1, y2), max(y1, y2)
        img_x1, img_y1, img_x2, img_y2 = self.image_area; margin = 0.1

        final_x1 = max(img_x1 - margin, x1_ord); final_y1 = max(img_y1 - margin, y1_ord)
        final_x2 = min(img_x2 + margin, x2_ord); final_y2 = min(img_y2 + margin, y2_ord)

        min_dim = self.handle_size * 1.5
        if final_x2 - final_x1 < min_dim or final_y2 - final_y1 < min_dim:
             if not self.crop_rect: self.clear_crop_rect(); return

        self.clear_crop_rect()

        self.crop_rect = self.canvas.create_rectangle(final_x1, final_y1, final_x2, final_y2, outline="white", width=2, tags=("crop_rect", "crop_element"))
        if self.current_aspect_ratio == "8:5 (horizontal)" and self.show_split_line:
            mid_x = (final_x1 + final_x2) / 2
            self.split_line = self.canvas.create_line(mid_x, final_y1, mid_x, final_y2, fill="white", dash=(4, 2), width=1, tags=("split_line", "crop_element"))

        hs = self.handle_size / 2
        handle_positions = {
            "nw": (final_x1, final_y1), "ne": (final_x2, final_y1), "sw": (final_x1, final_y2), "se": (final_x2, final_y2),
            "n": ((final_x1+final_x2)/2, final_y1), "s": ((final_x1+final_x2)/2, final_y2),
            "w": (final_x1, (final_y1+final_y2)/2), "e": (final_x2, (final_y1+final_y2)/2),
        }
        for position, (hx, hy) in handle_positions.items():
            handle = self.canvas.create_rectangle(hx-hs, hy-hs, hx+hs, hy+hs, fill="white", outline="black", width=1, tags=("handle", position, "crop_element"))
            self.handles[position] = handle

        if self.image_on_canvas:
             try: self.canvas.tag_lower(self.image_on_canvas, self.crop_rect)
             except tk.TclError: pass

    def clear_crop_rect(self):
        if self.canvas:
            try: self.canvas.delete("crop_element")
            except tk.TclError: pass
        self.crop_rect = None; self.split_line = None; self.handles = {}

    def raise_crop_elements(self):
        if self.save_mode != "crop" or not self.canvas: return
        try:
            if self.crop_rect: self.canvas.tag_raise(self.crop_rect)
            if self.split_line: self.canvas.tag_raise(self.split_line)
            for handle_id in self.handles.values():
                 if self.canvas.winfo_exists() and handle_id in self.canvas.find_all(): self.canvas.tag_raise(handle_id)
            if self.preview_frame: self.preview_frame.lift()
        except tk.TclError: pass

    def create_initial_crop_rect(self):
        if self.save_mode == "crop": self.update_crop_rect_aspect_ratio()

    def update_crop_rect_aspect_ratio(self):
        if not self.display_image_pil or self.save_mode != "crop":
            self.clear_crop_rect(); return

        img_x1, img_y1, img_x2, img_y2 = self.image_area
        img_w_canvas = img_x2 - img_x1; img_h_canvas = img_y2 - img_y1

        # Vérification correcte de la validité de la zone d'image
        if img_w_canvas <= 0 or img_h_canvas <= 0 or self.image_ratio <= 0:
            self.clear_crop_rect(); return

        aspect_tuple = self.aspect_ratios.get(self.current_aspect_ratio)
        if aspect_tuple:
            target_ratio = aspect_tuple[0] / aspect_tuple[1]
            current_ratio_on_canvas = img_w_canvas / img_h_canvas

            if current_ratio_on_canvas > target_ratio:
                rect_h = img_h_canvas; rect_w = rect_h * target_ratio
            else:
                rect_w = img_w_canvas; rect_h = rect_w / target_ratio
            rect_x1 = img_x1 + (img_w_canvas - rect_w) / 2; rect_y1 = img_y1 + (img_h_canvas - rect_h) / 2
            rect_x2 = rect_x1 + rect_w; rect_y2 = rect_y1 + rect_h
        else:
            rect_x1, rect_y1, rect_x2, rect_y2 = self.image_area
        self.create_crop_rect(rect_x1, rect_y1, rect_x2, rect_y2)

    def on_ratio_changed(self, event=None):
        new_ratio_name = self.ratio_var.get()
        if new_ratio_name != self.current_aspect_ratio:
            self.current_aspect_ratio = new_ratio_name
            if self.save_mode == "white_bars":
                self.save_mode = "crop"; self.processed_image = None
                self.display_image_pil = self.original_image
                self.remove_canvas_border(); self.ratio_menu.config(state="readonly")
                self.update_canvas()
            self.update_crop_rect_aspect_ratio(); self.raise_crop_elements(); self.update_preview()

    def get_handle_at_position(self, x, y):
        search_radius = self.handle_size / 2 + 2
        try:
            if not self.canvas: return None, None
            overlapping = self.canvas.find_overlapping(x-search_radius, y-search_radius, x+search_radius, y+search_radius)
            for item_id in overlapping:
                tags = self.canvas.gettags(item_id)
                if "handle" in tags:
                     for tag in tags:
                         if tag in self.handles and self.handles[tag] == item_id: return tag, item_id
        except tk.TclError: return None, None
        return None, None

    def is_inside_crop_rect(self, x, y):
        if not self.crop_rect or self.save_mode != "crop" or not self.canvas: return False
        try:
            coords = self.canvas.coords(self.crop_rect)
            if not coords: return False
            return coords[0] <= x <= coords[2] and coords[1] <= y <= coords[3]
        except tk.TclError: return False

    def on_press(self, event):
        if self.save_mode != "crop" or not self.crop_rect or not self.canvas:
            self.drag_data["item"] = None; return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        pos, handle_id = self.get_handle_at_position(x, y)

        if pos and handle_id:
            self.drag_data.update({"item": handle_id, "type": "handle", "position": pos})
            try: self.canvas.tag_raise(handle_id)
            except tk.TclError: pass
        elif self.is_inside_crop_rect(x, y):
            self.drag_data.update({"item": self.crop_rect, "type": "rect"})
            self.raise_crop_elements()
        else:
            self.drag_data["item"] = None; self.drag_data["type"] = None; return
        self.drag_data["x"] = x; self.drag_data["y"] = y

    def on_drag(self, event):
        if not self.drag_data.get("item") or not self.canvas: return

        current_x = self.canvas.canvasx(event.x); current_y = self.canvas.canvasy(event.y)
        dx = current_x - self.drag_data["x"]; dy = current_y - self.drag_data["y"]

        try: x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
        except (tk.TclError, IndexError, ValueError): self.drag_data["item"] = None; return

        img_x1, img_y1, img_x2, img_y2 = self.image_area

        fixed_ratio = False; target_ratio = None
        aspect_tuple = self.aspect_ratios.get(self.current_aspect_ratio)
        if aspect_tuple: fixed_ratio = True; target_ratio = aspect_tuple[0] / aspect_tuple[1]

        if self.drag_data["type"] == "handle":
            pos = self.drag_data["position"]; new_coords = [x1, y1, x2, y2]

            if "n" in pos: new_coords[1] += dy
            if "s" in pos: new_coords[3] += dy
            if "w" in pos: new_coords[0] += dx
            if "e" in pos: new_coords[2] += dx

            if fixed_ratio and target_ratio is not None:
                anchor_x, anchor_y = None, None
                fixed_x, fixed_y = None, None

                if pos == "nw": anchor_x, anchor_y = x2, y2
                elif pos == "ne": anchor_x, anchor_y = x1, y2
                elif pos == "sw": anchor_x, anchor_y = x2, y1
                elif pos == "se": anchor_x, anchor_y = x1, y1
                elif pos == "n": fixed_y = y2; new_coords[1] = min(new_coords[1], fixed_y -1)
                elif pos == "s": fixed_y = y1; new_coords[3] = max(new_coords[3], fixed_y +1)
                elif pos == "w": fixed_x = x2; new_coords[0] = min(new_coords[0], fixed_x -1)
                elif pos == "e": fixed_x = x1; new_coords[2] = max(new_coords[2], fixed_x +1)

                if pos in ['n', 's']:
                    new_h_temp = abs(fixed_y - new_coords[1]) if pos == 'n' else abs(new_coords[3] - fixed_y)
                    if new_h_temp < 1: new_h_temp = 1
                    new_w_adj = new_h_temp * target_ratio; center_x = (x1 + x2) / 2
                    new_coords[0] = center_x - new_w_adj / 2; new_coords[2] = center_x + new_w_adj / 2
                elif pos in ['w', 'e']:
                    new_w_temp = abs(fixed_x - new_coords[0]) if pos == 'w' else abs(new_coords[2] - fixed_x)
                    if new_w_temp < 1: new_w_temp = 1
                    new_h_adj = new_w_temp / target_ratio; center_y = (y1 + y2) / 2
                    new_coords[1] = center_y - new_h_adj / 2; new_coords[3] = center_y + new_h_adj / 2
                elif anchor_x is not None and anchor_y is not None:
                    pot_w = abs(anchor_x - (new_coords[0] if 'w' in pos else new_coords[2]))
                    pot_h = abs(anchor_y - (new_coords[1] if 'n' in pos else new_coords[3]))
                    if pot_w < 1: pot_w = 1;
                    if pot_h < 1: pot_h = 1
                    if pot_h / pot_w > 1 / target_ratio:
                        new_w_adj = pot_w; new_h_adj = new_w_adj / target_ratio
                    else:
                        new_h_adj = pot_h; new_w_adj = new_h_adj * target_ratio
                    if 'n' in pos: new_coords[1] = anchor_y - new_h_adj
                    else: new_coords[3] = anchor_y + new_h_adj
                    if 'w' in pos: new_coords[0] = anchor_x - new_w_adj
                    else: new_coords[2] = anchor_x + new_w_adj

            nc_x1, nc_y1, nc_x2, nc_y2 = new_coords
            nc_w_raw = nc_x2 - nc_x1; nc_h_raw = nc_y2 - nc_y1
            min_dim_final = self.handle_size * 0.5
            if nc_w_raw < min_dim_final or nc_h_raw < min_dim_final:
                 self.drag_data["x"] = current_x; self.drag_data["y"] = current_y; return

            nc_x1_ord, nc_x2_ord = min(nc_x1, nc_x2), max(nc_x1, nc_x2)
            nc_y1_ord, nc_y2_ord = min(nc_y1, nc_y2), max(nc_y1, nc_y2)

            final_x1 = max(img_x1, nc_x1_ord); final_y1 = max(img_y1, nc_y1_ord)
            final_x2 = min(img_x2, nc_x2_ord); final_y2 = min(img_y2, nc_y2_ord)

            if fixed_ratio and target_ratio is not None:
                 current_w_clamped = final_x2 - final_x1; current_h_clamped = final_y2 - final_y1
                 if current_h_clamped > 0.1 and current_w_clamped > 0.1 and abs(current_w_clamped / current_h_clamped - target_ratio) > 0.01:
                      if final_x1 == img_x1 or final_x2 == img_x2:
                           new_h_constrained = current_w_clamped / target_ratio
                           if pos in ['n', 'nw', 'ne']: final_y1 = max(img_y1, final_y2 - new_h_constrained)
                           else: final_y2 = min(img_y2, final_y1 + new_h_constrained)
                      elif final_y1 == img_y1 or final_y2 == img_y2:
                           new_w_constrained = current_h_clamped * target_ratio
                           if pos in ['w', 'nw', 'sw']: final_x1 = max(img_x1, final_x2 - new_w_constrained)
                           else: final_x2 = min(img_x2, final_x1 + new_w_constrained)
            self.create_crop_rect(final_x1, final_y1, final_x2, final_y2)

        elif self.drag_data["type"] == "rect":
            rect_w = x2 - x1; rect_h = y2 - y1
            new_x1 = max(img_x1, min(x1 + dx, img_x2 - rect_w))
            new_y1 = max(img_y1, min(y1 + dy, img_y2 - rect_h))
            new_x2 = new_x1 + rect_w; new_y2 = new_y1 + rect_h
            self.create_crop_rect(new_x1, new_y1, new_x2, new_y2)

        self.drag_data["x"] = current_x; self.drag_data["y"] = current_y
        self.update_preview()

    def on_release(self, event):
        if self.drag_data.get("item"):
            self.update_preview()
            if self.canvas and self.crop_rect:
                try:
                    coords = self.canvas.coords(self.crop_rect)
                    if coords: self.create_crop_rect(*coords); self.raise_crop_elements()
                except tk.TclError: pass
        self.drag_data = {"x": 0, "y": 0, "item": None, "type": None}

    def get_relative_crop_coords(self):
         if self.crop_rect and self.save_mode == "crop":
              try:
                   if not self.canvas: return None
                   crop_coords = self.canvas.coords(self.crop_rect); img_coords = self.image_area
                   if not crop_coords: return None

                   img_w_canvas = img_coords[2] - img_coords[0]; img_h_canvas = img_coords[3] - img_coords[1]
                   # Vérification correcte de la validité de la zone d'image
                   if img_w_canvas > 0 and img_h_canvas > 0 and self.image_ratio > 0:
                        c = crop_coords; i = img_coords
                        rel_x1 = max(0.0, min(1.0, (c[0]-i[0])/img_w_canvas))
                        rel_y1 = max(0.0, min(1.0, (c[1]-i[1])/img_h_canvas))
                        rel_x2 = max(0.0, min(1.0, (c[2]-i[0])/img_w_canvas))
                        rel_y2 = max(0.0, min(1.0, (c[3]-i[1])/img_h_canvas))
                        return (rel_x1, rel_y1, rel_x2, rel_y2)
              except tk.TclError: return None
         return None

    def restore_crop_rect_from_relative(self, crop_rel_coords):
         if crop_rel_coords and self.save_mode == "crop":
              rel_x1, rel_y1, rel_x2, rel_y2 = crop_rel_coords; img_coords = self.image_area
              img_w_canvas = img_coords[2] - img_coords[0]; img_h_canvas = img_coords[3] - img_coords[1]

              # Vérification correcte de la validité de la zone d'image
              if img_w_canvas > 0 and img_h_canvas > 0 and self.image_ratio > 0:
                   if rel_x1 > rel_x2: rel_x1, rel_x2 = rel_x2, rel_x1
                   if rel_y1 > rel_y2: rel_y1, rel_y2 = rel_y2, rel_y1
                   abs_x1 = img_coords[0] + rel_x1 * img_w_canvas; abs_y1 = img_coords[1] + rel_y1 * img_h_canvas
                   abs_x2 = img_coords[0] + rel_x2 * img_w_canvas; abs_y2 = img_coords[1] + rel_y2 * img_h_canvas
                   self.create_crop_rect(abs_x1, abs_y1, abs_x2, abs_y2)
              else: self.create_initial_crop_rect()
         elif self.save_mode == "crop": self.create_initial_crop_rect()
         else: self.clear_crop_rect()

    def update_preview(self):
        if not self.preview_frame or not self.preview_label_left: return
        self.preview_label_left.pack_forget(); self.preview_label_right.pack_forget()

        def resize_and_center(img_to_resize, target_w, target_h):
            if not img_to_resize: return None
            try:
                img_thumb = img_to_resize.copy(); img_thumb.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
                bg_mode = 'RGBA' if 'A' in img_to_resize.mode or (img_to_resize.mode == 'P' and 'transparency' in img_to_resize.info) else 'RGB'
                background = Image.new(bg_mode, (target_w, target_h), self.preview_bg_color)
                pos_x = (target_w - img_thumb.width)//2; pos_y = (target_h - img_thumb.height)//2

                if img_thumb.mode == 'RGBA':
                     mask = img_thumb.split()[-1]
                     if background.mode == 'RGBA': background.paste(img_thumb, (pos_x, pos_y), mask=mask)
                     else:
                         img_thumb_rgb = Image.new("RGB", img_thumb.size, self.preview_bg_color); img_thumb_rgb.paste(img_thumb, mask=mask); background.paste(img_thumb_rgb, (pos_x, pos_y))
                elif img_thumb.mode == 'P' and 'transparency' in img_thumb.info:
                     try: img_thumb_rgba = img_thumb.convert('RGBA'); mask = img_thumb_rgba.split()[-1]
                     except Exception: background.paste(img_thumb, (pos_x, pos_y)); return ImageTk.PhotoImage(background)
                     if background.mode == 'RGBA': background.paste(img_thumb_rgba, (pos_x, pos_y), mask=mask)
                     else: img_thumb_rgb = Image.new("RGB", img_thumb_rgba.size, self.preview_bg_color); img_thumb_rgb.paste(img_thumb_rgba, mask=mask); background.paste(img_thumb_rgb, (pos_x, pos_y))
                else:
                    background.paste(img_thumb.convert(background.mode) if img_thumb.mode != background.mode else img_thumb, (pos_x, pos_y))
                return ImageTk.PhotoImage(background)
            except Exception as e: print(f"Preview resize error: {e}"); return None

        source_image_for_preview = self.original_image
        is_split_mode = (self.save_mode == "crop" and self.current_aspect_ratio == "8:5 (horizontal)" and self.show_split_line)

        if self.save_mode == "white_bars" and self.processed_image:
            self.preview_photo_left = resize_and_center(self.processed_image, PREVIEW_WIDTH, PREVIEW_HEIGHT)
            self.preview_photo_right = None
            if self.preview_photo_left: self.preview_label_left.config(image=self.preview_photo_left, text=''); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            else: self.preview_label_left.config(image='', text="Erreur Aperçu Barres", compound="center", fg="red"); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            return

        if not source_image_for_preview:
            self.preview_photo_left=None; self.preview_photo_right=None; self.preview_label_left.config(image='', text="Pas d'image", compound="center", fg="grey"); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            return

        if not self.crop_rect or self.save_mode != "crop" or not self.canvas:
            self.preview_photo_left = resize_and_center(source_image_for_preview, PREVIEW_WIDTH, PREVIEW_HEIGHT)
            self.preview_photo_right = None
            if self.preview_photo_left: self.preview_label_left.config(image=self.preview_photo_left, text=''); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            else: self.preview_label_left.config(image='', text="Erreur Aperçu Orig.", compound="center", fg="red"); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            return

        try:
            rect_coords = self.canvas.coords(self.crop_rect)
            if not rect_coords or len(rect_coords)<4: raise ValueError("Coords crop invalides")
            x1c, y1c, x2c, y2c = rect_coords; ix1, iy1, ix2, iy2 = self.image_area
            if not (ix2 > ix1 and iy2 > iy1 and self.image_ratio > 0): raise ValueError("Zone image invalide")

            cx1r = x1c-ix1; cy1r = y1c-iy1; cx2r = x2c-ix1; cy2r = y2c-iy1
            # Protection contre la division par zéro
            if self.image_ratio <= 0: raise ValueError("Ratio d'image invalide")
            ox1 = int(cx1r/self.image_ratio); oy1 = int(cy1r/self.image_ratio)
            ox2 = int(cx2r/self.image_ratio); oy2 = int(cy2r/self.image_ratio)
            ow, oh = source_image_for_preview.size
            ox1 = max(0, min(ow, ox1)); oy1 = max(0, min(oh, oy1));
            ox2 = max(ox1, min(ow, ox2)); oy2 = max(oy1, min(oh, oy2))
            if ox1 >= ox2 or oy1 >= oy2: raise ValueError("Crop final invalide (dimensions nulles ou négatives)")
            crop_box = (ox1, oy1, ox2, oy2)

            if is_split_mode:
                split_point_x_orig = ox1 + (ox2-ox1)//2
                left_crop_box = (ox1, oy1, split_point_x_orig, oy2)
                right_crop_box = (split_point_x_orig, oy1, ox2, oy2)
                if left_crop_box[0]>=left_crop_box[2] or right_crop_box[0]>=right_crop_box[2]: raise ValueError("Split invalide (largeur nulle)")

                img_left_pil = source_image_for_preview.crop(left_crop_box)
                img_right_pil = source_image_for_preview.crop(right_crop_box)
                preview_w_half = (PREVIEW_WIDTH-PREVIEW_GAP)//2; preview_h_full = PREVIEW_HEIGHT
                self.preview_photo_left = resize_and_center(img_left_pil, preview_w_half, preview_h_full)
                self.preview_photo_right = resize_and_center(img_right_pil, preview_w_half, preview_h_full)

                if self.preview_photo_left and self.preview_photo_right:
                    self.preview_label_left.config(image=self.preview_photo_left, text=''); self.preview_label_right.config(image=self.preview_photo_right, text='')
                    self.preview_label_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, PREVIEW_GAP // 2))
                    self.preview_label_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(PREVIEW_GAP // 2, 0))
                else: raise ValueError("Erreur Aperçu Split (génération PhotoImage)")
            else:
                cropped_img_pil = source_image_for_preview.crop(crop_box)
                self.preview_photo_left = resize_and_center(cropped_img_pil, PREVIEW_WIDTH, PREVIEW_HEIGHT)
                self.preview_photo_right = None
                if self.preview_photo_left: self.preview_label_left.config(image=self.preview_photo_left, text=''); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
                else: raise ValueError("Erreur Aperçu Crop (génération PhotoImage)")
        except Exception as e:
            print(f"Erreur MàJ Aperçu (Cropper): {e}")
            self.preview_label_left.pack_forget(); self.preview_label_right.pack_forget()
            self.preview_label_left.config(image='', text="Erreur Aperçu", compound="center", fg="red"); self.preview_label_left.pack(fill=tk.BOTH, expand=True)
            self.preview_photo_left = None; self.preview_photo_right = None

    def toggle_flip(self):
        if self.original_image:
            self.flipped = not self.flipped
            try:
                self.original_image = ImageOps.mirror(self.original_image)
                if self.save_mode == "white_bars":
                    self.add_white_bars(force_recreate=True)
                else:
                    crop_rel = self.get_relative_crop_coords()
                    self.display_image_pil = self.original_image; self.update_canvas()
                    if crop_rel:
                        flipped_rel_x1 = 1.0 - crop_rel[2]; flipped_rel_x2 = 1.0 - crop_rel[0]
                        flipped_rel_coords = (min(flipped_rel_x1, flipped_rel_x2), crop_rel[1], max(flipped_rel_x1, flipped_rel_x2), crop_rel[3])
                        self.restore_crop_rect_from_relative(flipped_rel_coords)
                    else: self.create_initial_crop_rect()
                    self.raise_crop_elements()
                self.update_preview()
            except Exception as e: self.info_label.config(text=f"Erreur flip: {e}")

    def ignore_image(self):
        self.info_label.config(text=f"Image {os.path.basename(self.image_paths[self.current_image_index] if 0 <= self.current_image_index < len(self.image_paths) else '')} ignorée.")
        self.ignore_save = True; self.next_image(skip_save=True)

    def toggle_split_line(self):
        if self.current_aspect_ratio == "8:5 (horizontal)":
            self.show_split_line = not self.show_split_line
            if self.crop_rect and self.save_mode == "crop" and self.canvas:
                try: coords = self.canvas.coords(self.crop_rect); self.create_crop_rect(*coords); self.raise_crop_elements()
                except tk.TclError: pass
            self.update_preview()
        else: self.info_label.config(text="Ligne de séparation uniquement disponible pour le format 8:5.")

    def add_white_bars(self, force_recreate=False):
        if not self.original_image: self.info_label.config(text="Chargez une image d'abord."); return

        if self.save_mode != "white_bars" or force_recreate:
            try:
                orig_width, orig_height = self.original_image.size; target_ratio = 4 / 5
                if orig_width / orig_height > target_ratio:
                    final_width = orig_width; final_height = int(orig_width / target_ratio)
                else:
                    final_height = orig_height; final_width = int(orig_height * target_ratio)
                if final_width < 1 or final_height < 1: raise ValueError("Dims barres invalides")

                bg_mode = self.original_image.mode if self.original_image.mode in ['RGB', 'RGBA'] else 'RGB'
                white_background = Image.new(bg_mode, (final_width, final_height), (255, 255, 255))

                paste_x = (final_width - orig_width) // 2; paste_y = (final_height - orig_height) // 2
                if self.original_image.mode == 'RGBA':
                    white_background.paste(self.original_image, (paste_x, paste_y), mask=self.original_image.split()[-1])
                elif self.original_image.mode == 'P' and 'transparency' in self.original_image.info:
                     try: img_rgba = self.original_image.convert('RGBA'); white_background.paste(img_rgba, (paste_x, paste_y), mask=img_rgba.split()[-1])
                     except Exception: white_background.paste(self.original_image, (paste_x, paste_y))
                else:
                    white_background.paste(self.original_image.convert(bg_mode) if self.original_image.mode != bg_mode else self.original_image, (paste_x, paste_y))

                self.processed_image = white_background
                self.display_image_pil = self.processed_image
                self.save_mode = "white_bars"; self.info_label.config(text="Mode: Barres Blanches (format 4:5). Liseré noir visuel sur canevas.")
                self.ratio_menu.config(state="disabled"); self.clear_crop_rect(); self.update_canvas(); self.update_preview()
            except Exception as e:
                print(f"Erreur ajout barres blanches (Cropper): {e}")
                self.info_label.config(text=f"Erreur lors de l'ajout des barres blanches: {e}")
        else:
            self.save_mode = "crop"; self.processed_image = None
            self.display_image_pil = self.original_image; self.remove_canvas_border()
            self.ratio_menu.config(state="readonly"); self.update_canvas(); self.create_initial_crop_rect()
            self.raise_crop_elements(); self.update_preview(); self.info_label.config(text="Mode: Recadrage standard.")

    def apply_and_save_current_image(self):
        if self.ignore_save: self.ignore_save = False; return
        if self.current_image_index < 0 or self.current_image_index >= len(self.image_paths): return

        current_original_path = self.image_paths[self.current_image_index]
        source_for_info = self.original_image if self.save_mode == "crop" and self.original_image else self.processed_image
        if not source_for_info: return

        try:
            original_filename = os.path.basename(current_original_path)
            base_name, extension = os.path.splitext(original_filename)
            timestamp = int(time.time())
            image_to_save_pil = None; output_suffix = ""

            if self.save_mode == "white_bars":
                if not self.processed_image: self.info_label.config(text="Erreur: Image avec barres blanches manquante."); return
                image_to_save_pil = self.processed_image; output_suffix = f"_barres_{timestamp}"
            elif self.save_mode == "crop":
                if not self.crop_rect or not self.canvas or not self.original_image: self.info_label.config(text="Aucun recadrage/image originale."); return
                rect_coords = self.canvas.coords(self.crop_rect)
                if not rect_coords or len(rect_coords)<4: self.info_label.config(text="Erreur: Coords recadrage invalides."); return
                x1c, y1c, x2c, y2c = rect_coords; ix1, iy1, ix2, iy2 = self.image_area
                if not (ix2 > ix1 and iy2 > iy1 and self.image_ratio > 0): self.info_label.config(text="Erreur: Zone image invalide."); return
                cx1r = x1c-ix1; cy1r = y1c-iy1; cx2r = x2c-ix1; cy2r = y2c-iy1
                # Protection contre la division par zéro
                if self.image_ratio <= 0: self.info_label.config(text="Erreur: Ratio d'image invalide."); return
                ox1 = int(cx1r/self.image_ratio); oy1 = int(cy1r/self.image_ratio)
                ox2 = int(cx2r/self.image_ratio); oy2 = int(cy2r/self.image_ratio)
                ow, oh = self.original_image.size
                ox1 = max(0, min(ow, ox1)); oy1 = max(0, min(oh, oy1))
                ox2 = max(ox1, min(ow, ox2)); oy2 = max(oy1, min(oh, oy2))
                if ox1 >= ox2 or oy1 >= oy2: self.info_label.config(text="Erreur: Zone recadrage finale invalide."); return
                crop_box = (ox1, oy1, ox2, oy2)

                is_split_mode = (self.current_aspect_ratio == "8:5 (horizontal)" and self.show_split_line)
                if is_split_mode:
                    split_point_x_orig = ox1 + (ox2-ox1)//2
                    left_crop_box = (ox1, oy1, split_point_x_orig, oy2)
                    right_crop_box = (split_point_x_orig, oy1, ox2, oy2)
                    if left_crop_box[0]>=left_crop_box[2] or right_crop_box[0]>=right_crop_box[2]: self.info_label.config(text="Erreur: Division invalide."); return

                    left_img_pil = self.original_image.crop(left_crop_box)
                    right_img_pil = self.original_image.crop(right_crop_box)
                    new_left_filename = f"{base_name}_gauche_{timestamp}{extension}"
                    new_right_filename = f"{base_name}_droite_{timestamp}{extension}"
                    save_path_left = os.path.join(self.target_base_save_dir, new_left_filename)
                    save_path_right = os.path.join(self.target_base_save_dir, new_right_filename)
                    os.makedirs(os.path.dirname(save_path_left), exist_ok=True)

                    save_kwargs_l = self._get_save_kwargs(left_img_pil, extension)
                    save_kwargs_r = self._get_save_kwargs(right_img_pil, extension)
                    left_img_pil.save(save_path_left, **save_kwargs_l)
                    right_img_pil.save(save_path_right, **save_kwargs_r)

                    self.modified_paths_map[current_original_path] = [save_path_left, save_path_right]
                    self.info_label.config(text=f"Images divisées: {os.path.basename(save_path_left)}, {os.path.basename(save_path_right)}")
                    return
                else:
                    image_to_save_pil = self.original_image.crop(crop_box)
                    output_suffix = f"_recadre_{timestamp}"
            else: self.info_label.config(text="Mode de sauvegarde inconnu."); return

            if image_to_save_pil:
                new_filename = f"{base_name}{output_suffix}{extension}"
                save_path = os.path.join(self.target_base_save_dir, new_filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                save_kwargs = self._get_save_kwargs(image_to_save_pil, extension)
                image_to_save_pil.save(save_path, **save_kwargs)
                self.modified_paths_map[current_original_path] = save_path
                self.info_label.config(text=f"Image sauvegardée : {os.path.basename(save_path)}")
        except Exception as e:
            error_msg = f"Erreur sauvegarde (Cropper): {e}"; print(error_msg); traceback.print_exc()
            try: self.info_label.config(text=error_msg)
            except tk.TclError: pass

    def _get_save_kwargs(self, pil_image, extension_str):
        save_kwargs = {}
        ext_lower = extension_str.lower()
        if ext_lower in ['.jpg', '.jpeg']:
             save_kwargs['quality'] = 95
             icc_profile = pil_image.info.get('icc_profile')
             if icc_profile: save_kwargs['icc_profile'] = icc_profile
             save_kwargs['optimize'] = True
        elif ext_lower == '.png': save_kwargs['optimize'] = True
        return save_kwargs

    def next_image(self, skip_save=False):
        if not self.image_paths: self.info_label.config(text="Aucune image chargée."); return
        if self.current_image_index >= 0 and self.current_image_index < len(self.image_paths) and \
           not skip_save and not self.ignore_save:
            self.apply_and_save_current_image()
        elif self.ignore_save: self.ignore_save = False

        if self.current_image_index < len(self.image_paths) - 1:
            self.current_image_index += 1; self.load_current_image()
        else:
            self.info_label.config(text="Toutes les images ont été traitées. Cliquez sur 'Terminer et Appliquer'.")
            self.original_image = None; self.processed_image = None; self.display_image_pil = None
            if self.canvas: self.canvas.delete("all"); self.clear_crop_rect(); self.update_preview()
            self.remove_canvas_border()

    def prev_image(self):
        if not self.image_paths: self.info_label.config(text="Aucune image chargée."); return
        if self.current_image_index >= 0 and self.current_image_index < len(self.image_paths) and not self.ignore_save:
             self.apply_and_save_current_image()
        if self.ignore_save: self.ignore_save = False

        if self.current_image_index > 0:
            self.current_image_index -= 1
            self.ignore_save = True
            self.load_current_image()
        else: self.info_label.config(text="Ceci est la première image.")

# --- Application Entry Point ---
if __name__ == "__main__":
    print("=== Publication Organizer Start ===")
    app_instance = None; root_window = None
    try:
        root_window = tk.Tk()
        style = ttk.Style(root_window); style.theme_use('clam')

        default_root_bg = "SystemButtonFace" if sys.platform == "win32" else "#D9D9D9"
        try:
            current_root_bg = root_window.cget('bg')
            if current_root_bg != default_root_bg:
                 pass
            root_window.config(bg=default_root_bg)
        except tk.TclError:
            root_window.config(bg=default_root_bg)

        app_instance = PublicationOrganizer(root_window)
        if app_instance and hasattr(app_instance, '_initializing') and not app_instance._initializing and \
           root_window and root_window.winfo_exists():
            root_window.mainloop()
        elif root_window and root_window.winfo_exists():
             if app_instance and hasattr(app_instance, 'safe_destroy'): app_instance.safe_destroy()
             else: root_window.destroy()
    except Exception as main_error:
        print("ERREUR FATALE DANS LE BLOC MAIN:"); traceback.print_exc()
        if root_window and root_window.winfo_exists():
            parent_for_error = root_window
        else:
            parent_for_error = None

        try:
            messagebox.showerror("Erreur Fatale", f"Erreur critique inattendue:\n\n{main_error}\n\nL'application va se fermer.", parent=parent_for_error)
        except Exception: pass

        finally:
            if root_window and isinstance(root_window, tk.Tk) and root_window.winfo_exists():
                try: root_window.destroy()
                except Exception: pass
    finally:
        print("=== Publication Organizer Exit ===")

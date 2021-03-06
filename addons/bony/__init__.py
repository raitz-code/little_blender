# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


bl_info = {
    "name": "Bony",
    "description": "Provide a little help to work with bones",
    "author": "yhlai-code",
    "version": (0, 0, 1),
    "blender": (2, 80, 3),
    "location": "View3D > Sidebar > Bony",
    "category": "Rigging"
}

import bpy
import mathutils
from mathutils.kdtree import KDTree
import re
import math
from typing import Union, Tuple, List, Callable, Any
from functools import reduce

from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       FloatProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       PointerProperty,
                       )
from bpy.types import (Panel,
                       Menu,
                       Operator,
                       PropertyGroup,
                       )


# ------------------------------------------------------------------------
#   Utilities
# ------------------------------------------------------------------------

def move_modifier(obj, source, target, after=False, default_index=0):
    target_index = obj.modifiers.find(target)
    move_func = bpy.ops.object.modifier_move_to_index
    if target_index != -1:
        source_index = obj.modifiers.find(source)
        if source_index != -1:
            if source_index < target_index:
                if after:
                    move_func(modifier=source, index=target_index)
                else:
                    move_func(modifier=source, index=target_index-1)
            else:
                if after:
                    move_func(modifier=source, index=target_index+1)
                else:
                    move_func(modifier=source, index=target_index)
    else:
        move_func(modifier=source, index=default_index)


def active_and_others(ctx: bpy.types.Context) -> Union[Tuple[bpy.types.Object, List[bpy.types.Object]]]:
    active = ctx.active_object
    selected = ctx.selected_objects
    return active, [o for o in selected if o != active]


def only_two_selected(ctx: bpy.types.Context, type_active: str, type_other: str) -> bool:
    active, others = active_and_others(ctx)
    if active and others and len(others) == 1:
        if active.type == type_active and others[0].type == type_other:
            return True
    return False


def selected_one_or_more(ctx: bpy.types.Context, type: str) -> bool:
    selected = ctx.selected_objects

    if len(selected) == 0:
        return False
    for obj in selected:
        if obj.type != type:
            return False

    return True 
    

def for_each_selected(ctx: bpy.types.Context,
                      execute: Callable[[bpy.types.Object], Any]):
    objs = ctx.selected_objects
    for obj in objs:
        ctx.view_layer.objects.active = obj
        execute(obj)
    


# ------------------------------------------------------------------------
#   Copy Custom Shape
# ------------------------------------------------------------------------


class CopyCustomShapes(bpy.types.Operator):
    bl_idname = "bony.copy_custom_shapes"
    bl_label = "Copy Custom Shapes"
    bl_description = """Copy all the bone custom shapes from active object to all the other selected objects
                        (the whole armature structure needs to be identical) """
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected =  bpy.context.selected_objects
        source =  bpy.context.active_object
        
        if (source is None
                or source.type != 'ARMATURE'
                or len(selected) <= 1):
            return False
        for s in selected:
            if s.type != 'ARMATURE':
                return False

        return True


    def execute(self, context):
        def copy_custom_shapes(source: bpy.types.Pose, target: bpy.types.Pose):
            for source_bone in source.bones:
                target_bone = target.bones.get(source_bone.name)
                if target_bone:
                    target_bone.custom_shape = source_bone.custom_shape
        
        selected =  bpy.context.selected_objects
        source =  bpy.context.active_object

        for target in selected:
            if target is not source and source.pose and target.pose:
                copy_custom_shapes(source.pose, target.pose) 

        return {'FINISHED'}



# ------------------------------------------------------------------------
#   Copy Custom Properties
# ------------------------------------------------------------------------


class CopyCustomProperties(bpy.types.Operator):
    bl_idname = "bony.copy_custom_properties"
    bl_label = "Copy Custom Properties"
    bl_description = """Copy all the custom properties from active object to other selected objects"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        source, targets = active_and_others(context)
        return source is not None and len(targets) >= 1


    def execute(self, context):
        source, targets = active_and_others(context)

        props = source["_RNA_UI"]
        for t in targets:
            for p in props.keys():
                t[p] = source[p]

        bpy.context.view_layer.update()

        return {'FINISHED'}


# ------------------------------------------------------------------------
#   Rename Daz Bones
# ------------------------------------------------------------------------


class RenameDazBones(bpy.types.Operator):
    bl_idname = "bony.rename_daz_bones"
    bl_label = "Rename Daz Bones"
    bl_description = """Rename bones imported from Daz3D to follow Blender's naming convention
                        (e.g. lForearmBend -> ForearmBend_L) """
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected = bpy.context.selected_objects

        if len(selected) == 0:
            return False
        for obj in selected:
            if obj.type != 'ARMATURE':
                return False

        return True


    def execute(self, context):
        def repl(match):
            return f"{match.group(2)}_{match.group(1).upper()}"

        selected =  bpy.context.selected_objects

        for obj in selected:
            for bone in obj.pose.bones:
                p = re.compile(r"^(l|r)([A-Z]+.*)$")
                bone.name = p.sub(repl, bone.name)

        return {'FINISHED'}


# ------------------------------------------------------------------------
#   Symmetrize IK Constraints
#   To work around Blender's bug: https://developer.blender.org/T89715
# ------------------------------------------------------------------------

# TODO: Do all these things with one single click:
#       1. Symmetrize amature
#       2. Symmetrize IK constraints (what it does now)
#       3. Set inverse for Child Of constraints 
class SymmetrizeIKConstraints(bpy.types.Operator):
    bl_idname = "bony.symmetrize_ik_constraints"
    bl_label = "Symmetrize IK constraints"
    bl_description = """Blender's built-in symmetrize feature doesn't handle IK constraints correctly.
                        Use this to fix it."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected = bpy.context.selected_objects

        if len(selected) == 0:
            return False
        for obj in selected:
            if obj.type != 'ARMATURE':
                return False

        return True


    def execute(self, context):
        def symmetrize_ik_constraints(lb, rb):
            rb.ik_min_x = lb.ik_min_x
            rb.ik_max_x = lb.ik_max_x
            rb.ik_min_y = -lb.ik_max_y
            rb.ik_max_y = -lb.ik_min_y
            rb.ik_min_z = -lb.ik_max_z
            rb.ik_max_z = -lb.ik_min_z

        def get_right_bone_name(lbname):
            p = re.compile(r"^(.+)_L$")
            match = p.match(lbname)
            if match:
                return f"{match.group(1)}_R"
            else:
                return None

        bpy.ops.object.mode_set(mode = 'EDIT')

        selected =  bpy.context.selected_objects

        for obj in selected:
            bpy.ops.armature.select_all(action='SELECT')
            bpy.ops.armature.symmetrize(direction='POSITIVE_X')

        bpy.ops.object.mode_set(mode='OBJECT') 

        for obj in selected:
            for lb in obj.pose.bones:
                rbname = get_right_bone_name(lb.name)
                rb = obj.pose.bones.get(rbname) if rbname else None
                if rb:
                    rb.rotation_mode = lb.rotation_mode
                    symmetrize_ik_constraints(lb, rb)

        return {'FINISHED'}


# ------------------------------------------------------------------------
#   Clear Bone Transforms
# ------------------------------------------------------------------------

class ClearBoneTransforms(bpy.types.Operator):
    bl_idname = "bony.clear_bone_transforms"
    bl_label = "Clear Bone Transforms"
    bl_description = """Clear bone transforms, even the locked ones"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected = bpy.context.selected_objects

        if len(selected) == 0:
            return False
        for obj in selected:
            if obj.type != 'ARMATURE':
                return False

        return True


    def execute(self, context):
        def clear(bone: bpy.types.Bone):
            bone.location = [0, 0, 0]
            bone.rotation_quaternion = [1, 0, 0, 0]
            bone.scale = [1, 1, 1]

        selected =  bpy.context.selected_objects

        for obj in selected:
            for b in obj.pose.bones:
                clear(b)

        return {'FINISHED'}
            
# ------------------------------------------------------------------------
#   Reposition Bones
# ------------------------------------------------------------------------

class RepositionBones(bpy.types.Operator):
    bl_idname = "bony.reposition_bones"
    bl_label = "Reposition Bones"
    bl_description = """Reposition bones according shape keys"""
    bl_options = {'REGISTER', 'UNDO'}

    N_CLOSEST_VER = 10

    # Custom properties to store original coordinates
    # So we can reposition more than once
    bpy.types.PoseBone.bony_original_saved = bpy.props.BoolProperty()
    bpy.types.PoseBone.bony_original_co_head = bpy.props.FloatVectorProperty(subtype='TRANSLATION')
    bpy.types.PoseBone.bony_original_co_tail = bpy.props.FloatVectorProperty(subtype='TRANSLATION')

    @classmethod
    def poll(cls, context):
        return only_two_selected(context, "ARMATURE", "MESH")


    def execute(self, context):
        def calculate_new_co(co, group_size, evaluated_vertices, raw_vertices, kd):
            total_weight = 0
            total_delta = mathutils.Vector() 
            for (vc, i, dist) in kd.find_n(co, group_size):
                ev = evaluated_vertices[i]
                rv = raw_vertices[i]
                weight = (
                    1e4 if math.isclose(dist, 0) # don't give close vertices too much weight
                    else 1 / dist
                )
                total_weight += weight
                total_delta += (ev - rv) * weight
            
            return co + total_delta / total_weight


        armature, others = active_and_others(context)
        obj = others[0]
        mesh = obj.data

        # Generative modifier like subsurf changes vertices 
        if any([m.show_viewport and m.type != 'ARMATURE' for m in obj.modifiers]):
            self.report({'ERROR'}, "Please turn off the modifiers first.")
            return {'CANCELLED'}


        raw_vertices = []
        kd = KDTree(len(mesh.vertices))
        for i, v in enumerate(mesh.vertices):
            wv = obj.matrix_world @ v.co
            kd.insert(wv, i)
            raw_vertices.append(wv)
        kd.balance()

        # vertices deformed by shape keys
        evaluated_obj = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated_obj.to_mesh()
        evaluated_vertices = [evaluated_obj.matrix_world @ v.co for v in evaluated_mesh.vertices]

        bpy.ops.object.mode_set(mode='EDIT')

        for eb in armature.data.edit_bones:
            b = armature.pose.bones[eb.name]
            if b.bony_original_saved:
                # If stored original coordinates are found, just use them
                head_co = b.bony_original_co_head
                tail_co = b.bony_original_co_tail
            else:
                # Store original coordinates
                head_co = armature.matrix_world @ eb.head
                if(eb.name == "ForearmBend_L"):
                    print(head_co)
                tail_co = armature.matrix_world @ eb.tail
                b.bony_original_co_head = head_co
                b.bony_original_co_tail = tail_co
                b.bony_original_saved = True

                bpy.context.view_layer.update()

            new_head_co = calculate_new_co(head_co, RepositionBones.N_CLOSEST_VER,
                                           evaluated_vertices, raw_vertices, kd)
            new_tail_co = calculate_new_co(tail_co, RepositionBones.N_CLOSEST_VER,
                                           evaluated_vertices, raw_vertices, kd)

            eb.head = armature.matrix_world.inverted() @ new_head_co
            eb.tail = armature.matrix_world.inverted() @ new_tail_co


        bpy.context.view_layer.update()

        return {'FINISHED'}


# ------------------------------------------------------------------------
#   Transfer Rigging
# ------------------------------------------------------------------------

def transfer_rigging(source, target):
    def transfer_vertex_groups():
        dt = target.modifiers.new("DataTransfer", 'DATA_TRANSFER')
        dt.object = source
        dt.use_vert_data = True
        dt.data_types_verts = {'VGROUP_WEIGHTS'}
        dt.mix_mode = 'REPLACE'
        dt.mix_factor = 1.0
        bpy.context.view_layer.update()
        bpy.ops.object.modifier_move_to_index(modifier=dt.name, index=0)
        bpy.ops.object.datalayout_transfer(modifier=dt.name)
        bpy.ops.object.modifier_apply(modifier=dt.name)
        bpy.ops.object.vertex_group_remove_unused()


    def transfer_armature():
        # Remove existing armatures if any
        for m in target.modifiers:
            if m.type == 'ARMATURE':
                bpy.ops.object.modifier_remove(modifier=m.name)
        ar = target.modifiers.new("Armature", 'ARMATURE')
        source_ars = [m for m in source.modifiers if m.type == 'ARMATURE']
        if source_ars:
            s = source_ars[0]
            ar.object = s.object
        else:
            raise RuntimeError("Source has no armature!")
        bpy.context.view_layer.update()
        bpy.ops.object.modifier_move_to_index(modifier=ar.name, index=0)


    transfer_vertex_groups()
    transfer_armature()

        

class TransferRigging(bpy.types.Operator):
    bl_idname = "bony.transfer_rigging"
    bl_label = "Transfer Rigging"
    bl_description = """Transfer riggin from another mesh"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return  selected_one_or_more(context, 'MESH')


    def execute(self, context):
        settings = context.scene.bony_settings
        source = settings.transfer_source

        for_each_selected(context, lambda obj: transfer_rigging(source, obj))
        
        return {'FINISHED'}

            
            
# ------------------------------------------------------------------------
#   Apply Shape Keys
# ------------------------------------------------------------------------



def get_driver_of_shape_key(shape_key):
    key = shape_key.id_data
    p = re.compile(r'key_blocks\["(.+)"\]')
    fcurves = key.animation_data.drivers
    for f in fcurves:
        m = p.search(f.data_path)
        if m and m[1] == shape_key.name:
            return f.driver
    return None


# Doesn't detect circular dependency. Might cause infinite loop
def has_only_single_property_recur(shape_key):
    driver = get_driver_of_shape_key(shape_key)

    if not driver:
        return True

    for v in driver.variables:
        if v.type != 'SINGLE_PROP':
            return False

        for t in v.targets:
            data_path_head, _, _ = t.data_path.rpartition('.')
            if data_path_head:
                print(t.data_path)
                data_target = eval("t.id." + data_path_head) # Hacky.
                if isinstance(data_target, bpy.types.ShapeKey):
                    ret = has_only_single_property_recur(data_target)
                    if not ret:
                        return False

    return True


def apply_shape_key(obj):
    if hasattr(obj.data, "shape_keys"):
        obj.shape_key_add(name='CombinedKeys', from_mix=True)
        for shapeKey in obj.data.shape_keys.key_blocks:
            obj.shape_key_remove(shapeKey)


def merge_non_corrective_shape_keys(obj):
    MERGED_KEY_NAME = 'MergedKey'
    to_remove = []
    if hasattr(obj.data, "shape_keys"):
        obj.shape_key_add(name=MERGED_KEY_NAME, from_mix=True)
        for shape_key in obj.data.shape_keys.key_blocks[1:]: # Skip Basis
            if shape_key.name == MERGED_KEY_NAME:
                shape_key.value = 1
            elif has_only_single_property_recur(shape_key):
                to_remove.append(shape_key)
    
    for shape_key in to_remove:
        obj.shape_key_remove(shape_key)

    # Blend the new merged key into Basis 
    obj.active_shape_key_index = 0
    bpy.ops.object.editmode_toggle()
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.blend_from_shape(shape=MERGED_KEY_NAME)
    bpy.ops.object.editmode_toggle()
    merged = obj.data.shape_keys.key_blocks[MERGED_KEY_NAME]
    merged.value = 0
    obj.shape_key_remove(merged)


class ApplyShapeKeys(bpy.types.Operator):
    bl_idname = "bony.apply_shape_keys"
    bl_label = "Apply Shape Keys"
    bl_description = """Apply all shape keys for selected meshes"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected = bpy.context.selected_objects

        if len(selected) == 0:
            return False
        for obj in selected:
            if obj.type != 'MESH':
                return False

        return True

    def execute(self, context):
        for_each_selected(context, apply_shape_key)
        return {'FINISHED'}


class MergeNonCorrectiveShapeKeys(bpy.types.Operator):
    bl_idname = "bony.merge_non_corrective_shape_keys"
    bl_label = "Merge Non-Corrective Keys"
    bl_description = """Merge all corrective keys (e.g. Daz's JCM) into one"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        selected = bpy.context.selected_objects

        if len(selected) == 0:
            return False
        for obj in selected:
            if obj.type != 'MESH':
                return False

        return True


    def execute(self, context):
        for_each_selected(context, merge_non_corrective_shape_keys)
        return {'FINISHED'}



# ------------------------------------------------------------------------
#   Initialize Clothing
# ------------------------------------------------------------------------

class InitializeClothing(bpy.types.Operator):
    bl_idname = "bony.initialize_clothing"
    bl_label = "Initialize Clothing"
    bl_description = """Initialize a piece of clothing from selected part of character mesh
                        (Separate, apply shape keys, auto-mirror, fatten, solidify, etc)"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object.type == "MESH" and context.mode == "EDIT_MESH"


    def execute(self, context):
        def duplicate_separate_mesh():
            bpy.ops.mesh.select_mirror(axis={'X'}, extend=True)
            bpy.ops.mesh.duplicate(mode=1)
            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.editmode_toggle()
        
        def active_clothing():
            selected = context.selected_objects
            for obj in selected:
                if obj == context.active_object:
                    # The character model
                    obj.select_set(False)
                else:
                    # The clothing
                    context.view_layer.objects.active = obj
        
        def cleanup_clothing():
            obj = context.active_object
            obj.lock_location = [False, False, False]
            obj.lock_rotation = [False, False, False]
            obj.lock_scale = [False, False, False]

            # Apply mirror and remove solidify to avoid duplicate
            mirror = obj.modifiers.get("Mirror")
            if mirror:
                bpy.ops.object.modifier_apply(modifier=mirror.name)
            solidify = obj.modifiers.get("Solidify")
            if solidify:
                obj.modifiers.remove(solidify)

            bpy.ops.object.vertex_group_remove(all=True)

            for i in range(len(obj.material_slots)):
                bpy.ops.object.material_slot_remove({'object': obj})
            
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

            bpy.ops.mesh.customdata_custom_splitnormals_clear()


        def auto_mirror():
            automirror = context.scene.automirror
            automirror.axis = 'x'
            automirror.orientation = 'positive'
            automirror.cut = True
            automirror.threshold = 0
            automirror.Use_Matcap = True
            automirror.show_on_cage = True
            bpy.ops.object.automirror()

        def add_thickness():
            bpy.ops.object.editmode_toggle()
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.transform.shrink_fatten(
                value=0.005,
                use_even_offset=False,
                use_proportional_edit=False)
            bpy.ops.object.editmode_toggle()
            bpy.ops.object.modifier_add(type='SOLIDIFY')
            

        def prepare_modifiers():
            obj = context.active_object
            mirror = obj.modifiers.get("Mirror")
            if mirror:
                move_modifier(context.active_object, 'Mirror', "Armature")
            solidify = obj.modifiers.get("Solidify")
            if solidify:
                solidify.thickness = 0.005
                move_modifier(context.active_object, 'Solidify', "Armature", after=True)
            subdiv = obj.modifiers.get("Subdivision")
            if subdiv:
                subdiv.levels = 1
                bpy.ops.object.modifier_move_to_index(modifier="Subdivision", index=(len(obj.modifiers) - 1))
                
        
        duplicate_separate_mesh()
        active_clothing()
        apply_shape_key(context.active_object)
        cleanup_clothing()
        try:
            # Skip if Auto Mirro isn't installed
            auto_mirror()
        except AttributeError:
            pass
        add_thickness()
        prepare_modifiers()


        return {'FINISHED'}




# ------------------------------------------------------------------------
#   Main Panel
# ------------------------------------------------------------------------

class Bony_PT_Object(bpy.types.Panel):
    bl_idname = "BONY_PT_OBJECT"
    bl_label = "Bony Object Panel"
    bl_space_type = "VIEW_3D"   
    bl_region_type = "UI"
    bl_category = "Bony"
    bl_context = "objectmode"   


    @classmethod
    def poll(self, context):
        return context.active_object

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        settings = context.scene.bony_settings

        layout.label(text="Object:")
        col0 = layout.column(align=True)
        col0.operator(CopyCustomProperties.bl_idname, icon="PROPERTIES")

        layout.label(text="Bones: ")
        col1 = layout.column(align=True)
        col1.operator(CopyCustomShapes.bl_idname, icon="BONE_DATA")
        col1.operator(SymmetrizeIKConstraints.bl_idname, icon="BONE_DATA")
        col1.operator(ClearBoneTransforms.bl_idname, icon="OUTLINER_OB_ARMATURE")
        col1.operator(RepositionBones.bl_idname, icon="OUTLINER_OB_ARMATURE")

        box = col1.box()
        col1_1 = box.row()
        split = col1_1.split(factor=0.25)
        split.label(text="Source: ")
        split.prop_search(settings, 'transfer_source', context.scene, "objects", text="")
        box.operator(TransferRigging.bl_idname, icon="OUTLINER_OB_ARMATURE")

        layout.label(text="Mesh: ")
        col2 = layout.column(align=True)
        col2.operator(ApplyShapeKeys.bl_idname, icon="SHAPEKEY_DATA")
        col2.operator(MergeNonCorrectiveShapeKeys.bl_idname, icon="SHAPEKEY_DATA")

        layout.label(text="For Daz3D: ")
        col3 = layout.column(align=True)
        col3.operator(RenameDazBones.bl_idname, icon="BONE_DATA")

        layout.separator()

        
class Bony_PT_Mesh(bpy.types.Panel):
    bl_idname = "BONY_PT_MESH"
    bl_label = "Bony Mesh Panel"
    bl_space_type = "VIEW_3D"   
    bl_region_type = "UI"
    bl_category = "Bony"
    bl_context = "mesh_edit"   


    @classmethod
    def poll(self, context):
        return context.active_object

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        layout.label(text="Clothing: ")
        col1 = layout.column(align=True)
        col1.operator(InitializeClothing.bl_idname, text="Initialize Clothing", icon="MOD_CLOTH")

        layout.separator()



class BonySettings(bpy.types.PropertyGroup):
    transfer_source:  bpy.props.PointerProperty(type=bpy.types.Object, name='Transfer Source')


CLASSES_TO_REGISTER = [
    Bony_PT_Object,
    Bony_PT_Mesh,
    BonySettings,
    CopyCustomShapes,
    CopyCustomProperties,
    SymmetrizeIKConstraints,
    ClearBoneTransforms,
    TransferRigging,
    RenameDazBones,
    ApplyShapeKeys,
    MergeNonCorrectiveShapeKeys,
    InitializeClothing,
    RepositionBones,
]


def register():
    [bpy.utils.register_class(klass) for klass in CLASSES_TO_REGISTER]
    bpy.types.Scene.bony_settings = bpy.props.PointerProperty(type=BonySettings)


def unregister():
    try:
        [bpy.utils.unregister_class(klass) for klass in CLASSES_TO_REGISTER]
        del bpy.types.Scene.bony_settings
    except RuntimeError:
        pass
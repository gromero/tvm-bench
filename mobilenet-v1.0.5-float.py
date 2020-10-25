import os
import numpy as np
import tvm
from PIL import Image
from tvm import te
from tvm.contrib import graph_runtime
from tvm import relay
from tvm.runtime import container
from tvm.runtime import vm as vm_rt
from tvm.relay import testing
from tvm.relay import vm
from tvm.contrib.download import download_testdata
from util import load_test_image,download_model_zoo,parse_options, get_device_arch, get_device_attributes, get_device_type, get_tvm_target
import sys

argv=sys.argv[1:]

device = parse_options(argv)

model_dir ="/mobilenet_v1_0.5_128/"
model_name ="mobilenet_v1_0.5_128.tflite"

model_dir = download_model_zoo(model_dir, model_name)

tflite_model_file = os.path.join(model_dir, model_name)
tflite_model_buf = open(tflite_model_file, "rb").read()

# Get TFLite model from buffer
try:
    import tflite
    tflite_model = tflite.Model.GetRootAsModel(tflite_model_buf, 0)
except AttributeError:
    import tflite.Model
    tflite_model = tflite.Model.Model.GetRootAsModel(tflite_model_buf, 0)

dtype="float32"
quant_bool=True
width=128
height=128
image_data = load_test_image(dtype, width, height)

input_tensor = "input"
input_shape = (1, 128, 128, 3)
input_dtype = dtype

# Parse TFLite model and convert it to a Relay module
mod, params = relay.frontend.from_tflite(tflite_model,
                                         shape_dict={input_tensor: input_shape},
                                         dtype_dict={input_tensor: input_dtype})
desired_layouts = {'nn.conv2d': ['NCHW', 'default']}
seq = tvm.transform.Sequential([relay.transform.RemoveUnusedFunctions(),relay.transform.ConvertLayout(desired_layouts)])
with tvm.transform.PassContext(opt_level=3):
    mod = seq(mod)

tvm_target = get_tvm_target(device, get_device_type(), get_device_arch(), get_device_attributes())

tvm_targets = tvm.target.Target(tvm_target)
cpu_target = "llvm"
target_host=cpu_target

cpudevice = tvm.runtime.cpu()
ctx = tvm.runtime.context("cpu")

with tvm.transform.PassContext(opt_level=3):
    graph_mod = relay.build(mod, tvm_targets, params=params,target_host=target_host)

lib = graph_mod.get_lib()
params = graph_mod.get_params()
graph = graph_mod.get_json()

# Create a runtime executor module
module = graph_runtime.create(graph, lib, tvm.cpu())

# Feed input data
module.set_input(input_tensor, tvm.nd.array(image_data))

# Feed related params
module.set_input(**params)

ftimer = module.module.time_evaluator("run", ctx, number=1, repeat=10)
prof_res = np.array(ftimer().results) * 1000  # multiply 1000 for converting to millisecond
print("%-20s %-7s %-19s (%s)" % (model_name, device, "%.2f ms" % np.mean(prof_res), "%.2f ms" % np.std(prof_res)))
print(tvm_target)

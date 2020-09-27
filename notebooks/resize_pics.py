from PIL import Image
import os

basewidth = 375
PATH = '/home/dkbrz/github/folklore/villages_2/'
for fname in os.listdir(os.path.join(PATH, 'orig')):
    img = Image.open(os.path.join(PATH, 'orig', fname))
    wpercent = (basewidth/float(img.size[0]))
    hsize = int((float(img.size[1])*float(wpercent)))
    img = img.resize((basewidth,hsize), Image.ANTIALIAS)
    img.save(os.path.join(PATH, 'resize', fname.replace(".", "_375.")))
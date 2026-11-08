"""Small RGB keypoint network, shared by CUDA training and CPU deployment."""
import torch
from torch import nn

class Localizer(nn.Module):
    def __init__(self):
        super().__init__()
        self.net=nn.Sequential(nn.Conv2d(3,16,5,padding=2),nn.ReLU(),
            nn.Conv2d(16,24,5,padding=4,dilation=2),nn.ReLU(),
            nn.Conv2d(24,24,5,padding=4,dilation=2),nn.ReLU(),
            nn.Conv2d(24,16,3,padding=1),nn.ReLU(),nn.Conv2d(16,1,1))
    def forward(self,x):return self.net(x)

def decode(logits):
    # Subpixel centroid around the best peak. Returns pixels in the 320x240 image.
    b,_,h,w=logits.shape
    flat=logits[:,0].reshape(b,-1);index=flat.argmax(1)
    yy,xx=torch.meshgrid(torch.arange(h,device=logits.device),torch.arange(w,device=logits.device),indexing='ij')
    keep=(abs(xx[None]-index[:,None,None]%w)<=3)&(abs(yy[None]-index[:,None,None]//w)<=3)
    weights=torch.softmax(logits[:,0].masked_fill(~keep,-1e9).flatten(1),1).reshape(b,h,w)
    return torch.stack([(weights*xx).sum((1,2)),(weights*yy).sum((1,2))],1)*2+0.5

/* Narrow, lossless packet transport for C039 raw YUY2 + PCM, 100 ns PTS.
 * LGPL 2.1+; maintained with the application, not a general media format. */
#include "avformat.h"
#include "internal.h"
#include "libavutil/channel_layout.h"
#include "libavutil/intreadwrite.h"
#include "libavutil/mathematics.h"

typedef struct VhsContext { int64_t origin; unsigned frame_bytes; } VhsContext;
static const uint8_t magic[8] = { 'V','H','S','T','0','0','0','1' };

static int write_header(AVFormatContext *s)
{
    AVCodecParameters *v, *a;
    AVRational rate;
    if (s->nb_streams != 2) return AVERROR(EINVAL);
    v=s->streams[0]->codecpar; a=s->streams[1]->codecpar;
    rate=s->streams[0]->avg_frame_rate;
    if (v->codec_id != AV_CODEC_ID_RAWVIDEO || v->format != AV_PIX_FMT_YUYV422 ||
        v->width != 720 || v->height != 576 ||
        a->codec_id != AV_CODEC_ID_PCM_S16LE || a->sample_rate != 48000 || a->ch_layout.nb_channels != 2)
        return AVERROR(EINVAL);
    if (!rate.num || !rate.den) rate=(AVRational){25,1};
    av_reduce(&rate.num, &rate.den, rate.num, rate.den, INT_MAX);
    if (rate.num != 25 || rate.den != 1) return AVERROR(EINVAL);
    avpriv_set_pts_info(s->streams[0],64,1,10000000);
    avpriv_set_pts_info(s->streams[1],64,1,10000000);
    avio_write(s->pb,magic,8);
    avio_wl32(s->pb,v->width); avio_wl32(s->pb,v->height);
    avio_wl32(s->pb,rate.num); avio_wl32(s->pb,rate.den);
    avio_wl32(s->pb,48000); avio_wl32(s->pb,2);
    avio_wl32(s->pb,1); avio_wl32(s->pb,0); /* confirmed C039 TFF */
    avio_wl64(s->pb,0); /* common recording origin; persistent source uses zero */
    avio_flush(s->pb);
    return 0;
}
static int write_packet(AVFormatContext *s, AVPacket *p)
{
    if (p->stream_index < 0 || p->stream_index > 1 || p->pts == AV_NOPTS_VALUE ||
        p->duration < 0 || p->size <= 0 || p->size > 16*1024*1024) return AVERROR_INVALIDDATA;
    if ((p->stream_index == 0 && p->size != 720*576*2) ||
        (p->stream_index == 1 && p->size % 4)) return AVERROR_INVALIDDATA;
    avio_wl32(s->pb,MKTAG('P','K','T','1')); avio_wl32(s->pb,p->stream_index);
    avio_wl64(s->pb,p->pts); avio_wl64(s->pb,p->duration);
    avio_wl32(s->pb,p->size); avio_wl32(s->pb,0);
    avio_write(s->pb,p->data,p->size); avio_flush(s->pb);
    return s->pb->error;
}
static int probe(const AVProbeData *p) { return p->buf_size >= 8 && !memcmp(p->buf,magic,8) ? AVPROBE_SCORE_MAX : 0; }
static int read_header(AVFormatContext *s)
{
    VhsContext *c=s->priv_data;
    uint8_t b[48]; unsigned w,h,n,d,sr,ch,field,reserved;
    AVStream *v,*a;
    if (avio_read(s->pb,b,48)!=48 || (memcmp(b,magic,8) && memcmp(b,"VHST0002",8))) return AVERROR_INVALIDDATA;
    w=AV_RL32(b+8); h=AV_RL32(b+12); n=AV_RL32(b+16); d=AV_RL32(b+20);
    sr=AV_RL32(b+24); ch=AV_RL32(b+28); field=AV_RL32(b+32); reserved=AV_RL32(b+36);
    c->origin=AV_RL64(b+40);
    int v2 = !memcmp(b,"VHST0002",8);
    if (w!=720 || sr!=48000 || ch!=2) return AVERROR_INVALIDDATA;
    if (v2) {
        if (!((h==576 && n==25 && d==1) || (h==480 && n==30000 && d==1001)) ||
            (field!=1 && field!=2) || reserved!=1) return AVERROR_INVALIDDATA;
    } else if (h!=576 || n!=25 || d!=1 || field!=1 || reserved) return AVERROR_INVALIDDATA;
    c->frame_bytes=w*h*2;
    v=avformat_new_stream(s,NULL); a=avformat_new_stream(s,NULL);
    if (!v || !a) return AVERROR(ENOMEM);
    v->codecpar->codec_type=AVMEDIA_TYPE_VIDEO; v->codecpar->codec_id=AV_CODEC_ID_RAWVIDEO;
    v->codecpar->format=v2?AV_PIX_FMT_UYVY422:AV_PIX_FMT_YUYV422;
    v->codecpar->codec_tag=v2?MKTAG('U','Y','V','Y'):MKTAG('Y','U','Y','2');
    v->codecpar->width=w; v->codecpar->height=h; v->codecpar->field_order=field==2?AV_FIELD_BB:AV_FIELD_TT;
    v->sample_aspect_ratio=h==576?(AVRational){16,15}:(AVRational){8,9}; v->avg_frame_rate=v->r_frame_rate=(AVRational){n,d};
    a->codecpar->codec_type=AVMEDIA_TYPE_AUDIO; a->codecpar->codec_id=AV_CODEC_ID_PCM_S16LE;
    a->codecpar->sample_rate=sr; a->codecpar->bits_per_coded_sample=16;
    av_channel_layout_default(&a->codecpar->ch_layout,ch);
    avpriv_set_pts_info(v,64,1,10000000); avpriv_set_pts_info(a,64,1,10000000);
    return 0;
}
static int read_packet(AVFormatContext *s, AVPacket *p)
{
    VhsContext *c=s->priv_data;
    uint8_t b[32]; unsigned tag,index,size,reserved; int ret; int64_t pts,duration;
    ret=avio_read(s->pb,b,32);
    if (ret==0 || ret==AVERROR_EOF) return AVERROR_EOF;
    if (ret!=32) return AVERROR_INVALIDDATA;
    tag=AV_RL32(b); index=AV_RL32(b+4); pts=AV_RL64(b+8); duration=AV_RL64(b+16);
    size=AV_RL32(b+24); reserved=AV_RL32(b+28);
    if (tag!=MKTAG('P','K','T','1')) return AVERROR_INVALIDDATA;
    if ((c->origin>0 && pts<INT64_MIN+c->origin) || (c->origin<0 && pts>INT64_MAX+c->origin)) return AVERROR_INVALIDDATA;
    if (index>1 || !size || size>16*1024*1024 || reserved || pts==AV_NOPTS_VALUE || duration<0 ||
        (index==0 && size!=c->frame_bytes) || (index==1 && size%4)) return AVERROR_INVALIDDATA;
    ret=av_get_packet(s->pb,p,size);
    if (ret<0) return ret;
    if (ret!=size) { av_packet_unref(p); return AVERROR_INVALIDDATA; }
    p->stream_index=index; p->pts=p->dts=pts-c->origin; p->duration=duration; p->flags |= AV_PKT_FLAG_KEY;
    return 0;
}
const AVOutputFormat ff_vhsts_muxer = {
    .name="vhsts", .long_name=NULL_IF_CONFIG_SMALL("VHS timestamp packets v1"),
    .audio_codec=AV_CODEC_ID_PCM_S16LE, .video_codec=AV_CODEC_ID_RAWVIDEO,
    .write_header=write_header, .write_packet=write_packet, .flags=AVFMT_TS_NONSTRICT
};
const AVInputFormat ff_vhsts_demuxer = {
    .name="vhsts", .long_name=NULL_IF_CONFIG_SMALL("VHS timestamp packets v1"),
    .priv_data_size=sizeof(VhsContext), .read_probe=probe, .read_header=read_header, .read_packet=read_packet,
    .flags=AVFMT_TS_DISCONT
};

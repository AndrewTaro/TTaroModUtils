import "coui://gui/gameface/coherent_labs/cohtml.js";

const video = document.getElementById("video");
const videoUrl = context.videoUrl;

class VideoPlayerWidget {

	constructor(video, videoUrl) {
		this.video = video;
		this.video.src = videoUrl;
		this.resetVideo();
	}

	resetVideo() {
		this.video.currentTime = 0;
		this.video.play();
	}
}

const videoPlayerWidget = new VideoPlayerWidget(video, videoUrl);
// Local macOS fallback for the replay exporter, using the system H.264 encoder.
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 5) return 2;
        int width = atoi(argv[1]), height = atoi(argv[2]), fps = atoi(argv[3]);
        if (width <= 0 || height <= 0 || fps <= 0) return 2;
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[4]]];
        NSError *error = nil;
        AVAssetWriter *writer = [AVAssetWriter assetWriterWithURL:url fileType:AVFileTypeMPEG4 error:&error];
        if (!writer) { NSLog(@"%@", error); return 1; }
        NSDictionary *settings = @{AVVideoCodecKey: AVVideoCodecTypeH264, AVVideoWidthKey:@(width),
            AVVideoHeightKey:@(height), AVVideoCompressionPropertiesKey:@{AVVideoAverageBitRateKey:@6000000}};
        AVAssetWriterInput *input = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo outputSettings:settings];
        NSDictionary *attrs = @{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
            (id)kCVPixelBufferWidthKey:@(width), (id)kCVPixelBufferHeightKey:@(height)};
        AVAssetWriterInputPixelBufferAdaptor *adaptor = [AVAssetWriterInputPixelBufferAdaptor
            assetWriterInputPixelBufferAdaptorWithAssetWriterInput:input sourcePixelBufferAttributes:attrs];
        [writer addInput:input];
        if (![writer startWriting]) { NSLog(@"%@", writer.error); return 1; }
        [writer startSessionAtSourceTime:kCMTimeZero];
        size_t size = (size_t)width * height * 3;
        NSMutableData *rgb = [NSMutableData dataWithLength:size];
        uint8_t *src = rgb.mutableBytes;
        int frame = 0;
        size_t count;
        while ((count = fread(src, 1, size, stdin)) != 0) {
            if (count != size) return 1;
            @autoreleasepool {
                NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:30];
                while (!input.readyForMoreMediaData) {
                    if (writer.status != AVAssetWriterStatusWriting || deadline.timeIntervalSinceNow < 0) {
                        NSLog(@"Encoder unavailable: %@", writer.error); return 1;
                    }
                    [NSThread sleepForTimeInterval:.005];
                }
                CVPixelBufferRef buffer = NULL;
                if (CVPixelBufferPoolCreatePixelBuffer(NULL, adaptor.pixelBufferPool, &buffer) != kCVReturnSuccess) return 1;
                CVPixelBufferLockBaseAddress(buffer, 0);
                uint8_t *base = CVPixelBufferGetBaseAddress(buffer);
                size_t stride = CVPixelBufferGetBytesPerRow(buffer);
                for (int y = 0; y < height; ++y) {
                    uint8_t *row = base + stride * y, *s = src + (size_t)y * width * 3;
                    for (int x = 0; x < width; ++x, row += 4, s += 3) {
                        row[0] = s[2]; row[1] = s[1]; row[2] = s[0]; row[3] = 255;
                    }
                }
                CVPixelBufferUnlockBaseAddress(buffer, 0);
                BOOL accepted = [adaptor appendPixelBuffer:buffer withPresentationTime:CMTimeMake(frame++, fps)];
                CVPixelBufferRelease(buffer);
                if (!accepted) { NSLog(@"%@", writer.error); return 1; }
            }
        }
        [writer endSessionAtSourceTime:CMTimeMake(frame, fps)];
        [input markAsFinished];
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        [writer finishWritingWithCompletionHandler:^{dispatch_semaphore_signal(done);}];
        if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_SEC)) != 0) return 1;
        if (writer.status != AVAssetWriterStatusCompleted) { NSLog(@"%@", writer.error); return 1; }
        return 0;
    }
}

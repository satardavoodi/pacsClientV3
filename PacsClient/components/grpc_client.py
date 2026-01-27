# -*- coding: utf-8 -*-

import os
import grpc

from . import dicom_service_pb2
from . import dicom_service_pb2_grpc


class DicomGrpcClient:
    def __init__(self, host='localhost', port=50051):
        self.server_address = f"{host}:{port}"
        print('server_address:', self.server_address)
        self.channel = None
        self.stub = None
        self._connect()
        
    def _connect(self):
        """برقراری ارتباط با سرور gRPC"""
        try:
            self.channel = grpc.insecure_channel(self.server_address)
            self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)
            print(f"Connected to gRPC server at {self.server_address}")
        except Exception as e:
            print(f"Error connecting to gRPC server: {e}")
            self.channel = None
            self.stub = None

    def get_thumbnails(self, patient_id, study_uid):
        """دریافت تصاویر کوچک (thumbnails) از سرور"""
        if not self.stub:
            return None
            
        try:


            # request = dicom_service_pb2.ThumbnailRequest(
            #     patient_id=patient_id,
            #     study_uid=study_uid
            # )

            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=True
            )

            # print('\nreq:', request , type(request), '\t end req\n')

            # response = self.stub.GetThumbnails(request)
            response = self.stub.GetStudyThumbnails(request)
            # print('response:', response)
            result = {
                'patient_name': response.patient_name,
                'patient_id': response.patient_id,
                'study_date': response.study_date,
                'study_uid': response.study_instance_uid,
            #     'study_description': response.study_description,
            #     'accession_number': response.accession_number,
            #     'referring_physician_name': response.referring_physician_name,
                'thumbnails': []
            }

            # تبدیل پاسخ gRPC به دیکشنری
            #
            # print('result:', result)
            #
            # # تبدیل سری‌ها با ساختار جدید
            for series in response.series_thumbnails:
                series_data = {
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
            #         'protocol_name': series.protocol_name,
            #         'body_part_examined': series.body_part_examined,
            #         'manufacturer': series.manufacturer,
            #         'institution_name': series.institution_name,
                    'image_count': series.image_count,
            #         'thumbnail_base64': series.first_image_thumbnail_base64,
            #         # داده‌ها به فرمت قبلی برای سازگاری با کد موجود
            #         'image_data': series.first_image_thumbnail_base64,
                    'thumbnail_path': series.thumbnail_path,
                    'thumbnail_data': series.thumbnail_data,
                }
                result['thumbnails'].append(series_data)

            # for series in response.series_thumbnails:
            #     # if series.thumbnail_data:
            #         filename = f"series_{series.series_number}.jpg"
            #         with open(filename, "wb") as f:
            #             f.write(series.thumbnail_data)
            #         print(f"Saved: {filename}")

            # print('resulttt:', result)
            return result
        except grpc.RpcError as e:
            status_code = e.code()
            details = e.details()
            print(f"gRPC Error: {status_code}, {details}")
            return None
        except Exception as e:
            print(f"Error getting thumbnails: {e}")
            return None

    def get_dicom_images(self, patient_id, study_uid, series_uid, save_dir):
        """دریافت تصاویر DICOM از سرور به صورت استریم"""
        if not self.stub:
            return {'images': [], 'error': 'Not connected to server'}
            
        try:
            request = dicom_service_pb2.DicomImageRequest(
                patient_id=patient_id,
                study_uid=study_uid,
                series_uid=series_uid
            )
            
            # اطمینان از وجود دایرکتوری ذخیره‌سازی
            series_dir = os.path.join(save_dir, study_uid, series_uid)
            os.makedirs(series_dir, exist_ok=True)
            
            print(f"درخواست تصاویر برای سری {series_uid} - مسیر ذخیره: {series_dir}")
            
            # دریافت استریم پاسخ
            received_files = []
            error = None
            
            try:
                for response in self.stub.GetDicomImages(request):
                    sop_uid = response.sop_instance_uid
                    instance_number = response.instance_number
                    image_data = response.image_data
                    file_name = response.file_name
                    
                    # ذخیره فایل
                    file_path = os.path.join(series_dir, file_name)
                    with open(file_path, 'wb') as f:
                        f.write(image_data)
                    
                    print(f"تصویر {file_name} با حجم {len(image_data)} بایت در {file_path} ذخیره شد")
                    
                    received_files.append({
                        'sop_instance_uid': sop_uid,
                        'instance_number': instance_number,
                        'file_path': file_path,
                        'file_name': file_name
                    })
                
                print(f"در مجموع {len(received_files)} تصویر دریافت شد")
                
            except grpc.RpcError as e:
                error = f"خطای gRPC: {e.code()}, {e.details()}"
                print(error)
            
            result = {
                'images': received_files,
                'error': error
            }
            
            return result
        except Exception as e:
            print(f"خطا در تابع get_dicom_images: {e}")
            import traceback
            traceback.print_exc()
            return {'images': [], 'error': str(e)}

    def close(self):
        """بستن ارتباط با سرور"""
        if self.channel:
            self.channel.close()
            self.channel = None
            self.stub = None 
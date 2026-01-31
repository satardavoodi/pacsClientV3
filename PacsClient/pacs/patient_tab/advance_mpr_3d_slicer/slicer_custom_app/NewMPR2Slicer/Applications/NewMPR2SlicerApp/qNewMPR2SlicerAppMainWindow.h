/*==============================================================================

  Copyright (c) Kitware, Inc.

  See http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Julien Finet, Kitware, Inc.
  and was partially funded by NIH grant 3P41RR013218-12S1

==============================================================================*/

#ifndef __qNewMPR2SlicerAppMainWindow_h
#define __qNewMPR2SlicerAppMainWindow_h

// NewMPR2Slicer includes
#include "qNewMPR2SlicerAppExport.h"
class qNewMPR2SlicerAppMainWindowPrivate;

// Slicer includes
#include "qSlicerMainWindow.h"

class Q_NEWMPR2SLICER_APP_EXPORT qNewMPR2SlicerAppMainWindow : public qSlicerMainWindow
{
  Q_OBJECT
public:
  typedef qSlicerMainWindow Superclass;

  qNewMPR2SlicerAppMainWindow(QWidget *parent=0);
  virtual ~qNewMPR2SlicerAppMainWindow();

public slots:
  void on_HelpAboutNewMPR2SlicerAppAction_triggered();

protected:
  qNewMPR2SlicerAppMainWindow(qNewMPR2SlicerAppMainWindowPrivate* pimpl, QWidget* parent);

private:
  Q_DECLARE_PRIVATE(qNewMPR2SlicerAppMainWindow);
  Q_DISABLE_COPY(qNewMPR2SlicerAppMainWindow);
};

#endif
